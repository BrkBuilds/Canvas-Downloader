---
paths:
  - "core/canvas_auth.py"
  - "core/browser_login.py"
  - "core/handoff.py"
  - "core/token_mint.py"
  - "ui/auth.py"
  - "start.py"
  - "dev.py"
  - "extension/**"
  - "scripts/check_handoff.py"
  - "scripts/build_extension_hosts.py"
---

# Signing in to Canvas with a browser session

> Extracted from CLAUDE.md. Loads only when Claude opens a matching file.
> Each entry states the mechanism, the measurement, and why the obvious fix is wrong.

## Why this exists, and why it is not optional (2026-09-11)
Instructure shipped two admin switches in **September 2025** - *Limit personal
access token creation to Admins* and *Restrict students and observers from
creating personal access tokens* - and the **April 2026 breach** (ShinyHunters,
~3.65 TB, 8,809 institutions) gave every Canvas administrator in the world a
reason to turn them on. CBS turned them on in September 2026. So the token
field is not merely higher-friction for a growing share of users: it is a
**dead end**, and no amount of better copy fixes that.
- **OAuth2 does NOT rescue it, and this is the most important negative result
  here.** `Canvas::OAuth::Provider#can_issue_token?` short-circuits on
  `key.trusted?` (a flag only Instructure can set) and otherwise falls through
  to `AccessToken.new(user:).grants_right?(logged_in_user, :create)` - the very
  same policy that reads `limit_personal_access_tokens?`. A third-party
  developer key therefore fails at a restricted institution with
  `client_not_allowed_for_user`. Read from `canvas-lms` master, 2026-09-11.
- **Session-cookie auth is a different code path entirely.**
  `AuthenticationMethods#load_user` tries a JWT, then an access token, and then
  falls back to `PseudonymSession.find_with_validation`. Nothing in that path
  consults the token-creation policy. It is also, literally, the mechanism every
  Canvas downloader extension in the Chrome Web Store already uses.

## The measurements this rests on - do not re-derive them
All taken 2026-09-11 against production Canvas.
- **The production session cookie is `canvas_session`**, not the open-source
  default `_normandy_session` (Instructure overrides the key from Consul, which
  `config/initializers/session_store.rb` explicitly allows). Measured on
  `cbs.instructure.com`: `Set-Cookie: canvas_session=...; path=/; secure;
  httponly; samesite=none`, alongside `log_session_id` (HttpOnly) and
  `_csrf_token` (**not** HttpOnly - that is how Canvas' own frontend reads it
  back for `X-CSRF-Token`). Both names are accepted so a self-hosted Canvas is
  not silently unsupported.
- **HttpOnly is why `document.cookie` and any JS bridge are useless here**, and
  why the native cookie store is the only route: WebView2's `CookieManager` and
  WKWebView's `WKHTTPCookieStore` both return HttpOnly cookies, and pywebview
  normalises both to a list of `http.cookies.SimpleCookie`.
- **CSRF is a non-issue for this app.** `Canvas::RequestForgeryProtection#
  verified_request?` is true for `request.get?`, and Canvas Downloader only
  ever reads. A non-GET would need the `_csrf_token` cookie echoed as
  `X-CSRF-Token`; nothing does.
- **Canvas publishes its own rate limit on every response** -
  `x-rate-limit-remaining: 700.0` and `x-request-cost: 0.0103` - so the engine
  can pace itself rather than discovering the ceiling by failing.
- **There are no CORS headers on `/api/v1`**, which is why the extensions need
  a `declarativeNetRequest` rule for `canvas-user-content.com` and a native
  client needs nothing.
- **CBS resolves `canvas.cbs.dk` -> `cbscanvas.instructure.com` and
  authenticates through `login.microsoftonline.com/<tenant>/saml2`** (Entra
  SAML). Microsoft has standardised its own Entra sign-in on WebView2, so an
  embedded window is the path Microsoft chose rather than one it blocks.
  **CORRECTED 2026-09-12 - Google is NOT the exception on Windows.** This said
  Google blocks embedded webviews and that its institutions were unservable.
  Measured through the app's own web view: WebView2's UA is indistinguishable
  from Edge and Google's sign-in form renders normally. See "GOOGLE IS NOT
  BLOCKED ON WINDOWS" below. macOS is still open.

## Why not read the user's real browser's cookies - closed, do not re-open
Dead on both platforms at once, and each half was verified before the design
was chosen: **Chrome 127** (July 2024) bound the cookie key to the browser
process with App-Bound Encryption, so a perfect copy of the database decrypts
to nothing even as administrator; **Chrome 136** (2025) then stopped honouring
`--remote-debugging-port` on the default profile, explicitly because attackers
were using it for cookie theft after ABE; Edge is Chromium and inherits both;
**Safari's** jar needs Full Disk Access. Firefox still works and Firefox is not
a market. It is also, behaviourally, exactly what an infostealer does - not a
pattern to ship in a signed Store app.

## The credential is a VALUE, and that is what made this a small change
`core/canvas_auth.py:CanvasCredential` carries how to authenticate; `coerce()`
turns a legacy token string, `None`, or a credential into one. Every
authenticated path in the app already funnelled through
`CanvasManager(api_key, api_url)` - **13 construction sites** - so making the
VALUE carry the answer meant none of them had to ask "am I on cookies?". Asking
at each site is how the next auth fix lands on some and not others, which is
this repo's most expensive recurring defect.
- **It is deliberately NOT a `str` subclass.** That would have let every
  existing site keep working *silently* until something called `.strip()`, got
  a plain `str` back, and degraded to an unauthenticated request reported as
  "your token was revoked". A distinct type fails loudly at the one site that
  misuses it.
- **`st.session_state['api_token']` holds a plain `str` in token mode and the
  OBJECT only in browser mode.** The existing path is byte-for-byte unchanged.
- **`credential_of(manager)` is the one accessor** for modules outside `core`
  (Panopto discovery, the Panopto runner, sync analysis) that are handed a
  manager by their caller and cannot assume it is the real class - the test
  suite passes stand-ins carrying only `api_key`. Its fallback is deliberately
  narrow: it applies when there is no credential object at all, never when
  there is an empty one, because empty is a real answer ("not signed in").
- **`CanvasManager.auth` and `.api_key` are CLASS-level defaults**, so an
  instance built with `__new__` (which several tests do) still has them. An
  AttributeError there surfaces inside a download worker as *"could not fetch
  items for module"*, which names the wrong cause entirely.

### The cookie must never leave the Canvas host
Canvas file URLs redirect onto a CDN it does not own
(`*.canvas-user-content.com`, inst-fs). A cookie with **no domain** is sent to
every host a session touches, so `cookies={...}` on either `requests` or
`aiohttp` hands a third party a complete Canvas login, silently, on every file
of every download. Both client builders therefore install a **domain-scoped**
jar: `aiohttp.CookieJar.update_cookies(..., response_url=...)` and
`RequestsCookieJar.set(..., domain=...)`. `aiohttp.CookieJar()` **binds to a
running event loop at construction**, which is satisfied because both call
sites build their session inside an `async def` - stated in the docstring so a
future caller preparing kwargs synchronously does not rediscover it.

### Browser mode must send NO Authorization header
Not tidiness. `load_pseudonym_from_access_token` runs **before** Canvas looks at
the session, and a token it cannot accept - an empty one included - raises
there and answers 401. So a stray bearer beside a perfectly good cookie breaks
the login completely, and breaks it in a way that reads as "your session
expired". `_SessionCookieRequester` overrides `Requester.request` to force
`use_auth=False` rather than blanking the token, so no Authorization header can
be formatted even on the endpoints canvasapi reaches through its own
paginated-list plumbing.

## Contracts the old `str` credential satisfied silently
Both of these SHIPPED and were found by driving the real app against real
Canvas. They are the cost of changing the type of a value 13 sites carry.
- **HASHABILITY.** `core/course_cache.py` keys its cache on `(token, url)`. A
  frozen dataclass holding a `dict` is unhashable, so the lookup raised
  `TypeError` deep inside the fetch - reported to the user as **"We couldn't
  reach Canvas"**, on a screen whose sidebar already said "Logged in as Birk".
  `cookies` is therefore `field(..., hash=False)`: excluded from the hash, kept
  in `__eq__`, so two sessions for one host collide in the bucket and still
  compare unequal, and a renewed session gets its own cache entry instead of
  serving the expired one's courses.
- Census taken at the same time and CLEAN, so do not repeat it: nothing
  serialises `st.session_state` wholesale, `course_cache` is the app's only
  cache, and `core/health_log.py`'s `session_state.json` is its own snapshot.

## The web view profile must SURVIVE the session
pywebview defaults to `private_mode=True`, which runs WebView2 InPrivate
against a temp directory thrown away on exit, and **both settings are
process-global** (`_state`, not per window) - so `start.py` is the only place
either can be set. Without `private_mode=False` **and** a `storage_path` the
sign-in works and is forgotten on every launch: more friction than the token it
replaces, with nothing failing anywhere.
- Consequence, documented rather than discovered later: pywebview's own
  `clear_user_data()` teardown runs in private mode ONLY, so it no longer
  fires. `_terminate_child_processes()` already reaps the whole tree on every
  exit path, which is the stronger guarantee.
- It degrades rather than fails: an unwritable profile directory falls back to
  private mode and the app still launches.
- The profile holds the LIVE cookies of the user's Canvas **and** identity
  provider sessions, so it is the most sensitive thing the app writes.
  `webview/` is gitignored; a dev run puts it in the repo root.

## The silent phase, and the bug that shipped inside it
`_worker` opens the window **hidden** and gives it `SILENT_TIMEOUT` (15s) in
both modes, because the silent attempt is the same either way: navigate, and
see whether the institution's SSO session carries us back to Canvas without
asking. Only what happens when it EXPIRES differs - an interactive login shows
the window and switches to `INTERACTIVE_TIMEOUT`, a silent one gives up.
- **Giving an interactive login the long clock up front is a TOTAL failure of
  the feature and no unit test saw it.** The window stays hidden for ten
  minutes, so the user clicks "Sign in with Canvas" and nothing ever appears.
  51 unit tests and a 22/23 mutation pass passed over it; the real app showed
  it in 75 seconds. **This is the entry that justifies the "verify in the REAL
  app" rule for this subsystem.**
- **Success is detected by the REAL thing, not by JavaScript.** Navigating to
  `/api/v1/users/self` and reading the JSON depends on whether the web view
  renders `application/json` inline; injecting a `fetch()` depends on
  pywebview's bridge surviving Canvas' CSP. Neither is worth betting a login
  on. Instead: once the window is on the Canvas origin, harvest the cookies and
  **make an actual API call from Python with them**. That is exactly what the
  downloader will do for the rest of the session, needs no JS, and behaves
  identically on both platforms.
- **A vanity address is resolved BEFORE the window opens**, through
  `CanvasManager`'s own resolver rather than a second copy of that rule. Twice
  load-bearing: `canvas.cbs.dk` redirects to `cbscanvas.instructure.com` and the
  cookies belong to the canonical host, and the "are we on Canvas yet?" test
  compares hosts - against the typed host it never matches and the sign-in can
  never finish.
- **`is_available()` answers False for the first ~2 seconds of a launch**,
  because pywebview sets the module-global `guilib` part way through `start()`.
  Unreachable in practice (the login page is not up that fast and the user must
  type an address first), but a probe written without waiting for it reports a
  false negative.

## A finished sign-in belongs to the APP, not to one Streamlit session
The sign-in state is process-global (a worker thread has no `ScriptRunContext`)
while "am I waiting?" is per SESSION, so the two come apart: reload the window
mid-sign-in, or have a second session open, and the login completes into a flag
nobody is holding. **Observed in the real app** - the user finished signing in
at CBS, came back, and the app was still on the login screen with a perfectly
good session in hand. `adopt_pending_browser_login` therefore reads the status
BEFORE the pending flag is allowed to end the function. Same lesson, same
shape, as `unlocked_token()` not consuming its result.

## Logging out means logging out
Three defects, all reported by the product owner from the real app, all from
the same root: the app treated "no stored session" as "renew it".
- **No stored credential must NEVER arm a hidden renewal.** That state *is*
  what logging out looks like, and the attempt the user never made then fails
  and announces *"Canvas sign-in did not finish"* on a screen they reached on
  purpose. The renewal flag is set INSIDE the branch that found a credential.
- **A failed HIDDEN renewal is not announced at all.** An expired session or a
  dropped network is the ordinary way of arriving at the login screen;
  `browser_login.was_interactive()` gates the notice so only an attempt the
  user started can produce one.
- **Logout prefills the Canvas address**, which `force_reauth` had done since
  it was written and logout never did - so signing out dropped the user on a
  login screen that had forgotten their school while an *expired token*
  remembered it. The address is in the config either way; this only decides
  whether the app shows what it already knows.
- **Logout also clears the web view's cookies** (`browser_login.clear_session()`
  -> profile-wide `clear_cookies()`). Clearing only the credential store would
  leave a signed-in profile behind, so the next launch signs straight back in -
  on a shared machine, as the previous user.

## The UI
- **The control is a second `st.form_submit_button`**, because inside `st.form`
  a plain `st.button` cannot rerun - a fact this file's siblings record at three
  other call sites. It sits ABOVE the token field: for a growing number of
  institutions the field below is not an alternative, it is a dead end.
- **No `help=` on it.** A tooltip wraps the button element in a
  `stTooltipHoverTarget` and silently drops Streamlit's own sizing, so it would
  render short beside its sibling. The explanation is a caption underneath,
  gated on the help-text setting; the "or use an access token" divider is
  structural and never gated.
- **The notice reuses the Keychain notice's `.kc-*` skin** rather than adding a
  near-identical second palette, and its stylesheet lives in the login page's
  UNCONDITIONAL block. The poll fragment emits **exactly one element in every
  state** and writes nothing else to the event container.

## Known, stated rather than fixed
- **No Chrome autofill.** The web view has its own profile, so saved passwords
  and autofill from the user's real browser are not available; only
  Windows-stored passkeys carry over. Reported as "a bit of a hassle" on first
  sign-in. It costs nothing on later launches, because the session persists.
- **On a heavily loaded machine the window can appear mid-navigation**, showing
  the browser's own error page (observed: `ERR_NAME_NOT_RESOLVED` for
  `login.microsoftonline.com`, which then resolved and loaded normally).
  `SILENT_TIMEOUT` is wall-clock, not "has the page settled".
- ~~**Google-SSO institutions are not served by this route**~~ - **WRONG on
  Windows, corrected 2026-09-12 by measurement; see the section below.** The
  companion-extension fallback the research brief proposed is therefore not
  needed on Windows and remains unbuilt.
- **macOS is unverified.** Every primitive used is the documented
  cross-platform pywebview API and the Cocoa backend marshals window creation
  onto the main thread, but nothing here has been driven on a Mac.

## Coverage
`tests/test_browser_login.py` (61) and `scripts/_mutate_browser_login.py` -
**31/32 caught**, the survivor a documented equivalent - so re-run the mutation
pass rather than just the suite. Verified end to end in the real app against
real CBS Canvas: the CBS login rendered in the app's own window, sign-in
completed, and a cold relaunch **signed in silently in 6 seconds and listed 14
courses** with no token anywhere.

# The 2026-09-11 audit: driven against REAL Canvas, the real engine, the real window

Everything below was measured, not reasoned. Where a claim could not be
measured it says so. **Do not re-derive any of it.**

## PANOPTO CANNOT WORK ON A SESSION - Canvas requires a token to mint a launch
Every Panopto path starts at `sessionless_launch`, and Canvas refuses that
endpoint outright without an access token. This is Canvas' own code, not a
permission quirk of one course (`app/controllers/lti/concerns/sessionless_launches.rb`):

    def generate_session_token
      # only allow from API, and not from files domain
      raise UnauthorizedClient unless @access_token

- **Measured on the real account**: all 36 Panopto module items of course 43660,
  both URL forms the app builds (`launch_type=module_item&module_item_id=…&id=…`
  and `?id=<tool>&url=…LTI.aspx`), every one **403 `user not authorised to
  perform that action`** - while `users/self` and `courses/43660/files` on the
  SAME session answer 200. So it is the endpoint, not the account.
- **The 403 is raised by `rescue UnauthorizedClient -> render_unauthorized_action`
  inside `generate_common_sessionless_launch`.** Reading only
  `generate_sessionless_launch` or the `before_action` list does not show it -
  the guard is two calls down, in the concern.
- **THE WORKING ROUTE, PROVEN END TO END.** A student watches these lectures in
  a browser, so the *in-app* launch works on a session. Starting the app's own
  form chain at the module-item page, with the Canvas credential on its
  DOMAIN-SCOPED jar:

      /courses/43660/modules/items/1087340
        -> /api/lti/authorize
        -> cbs.cloud.panopto.eu/Panopto/Pages/Embed.aspx
      delivery id b58f9a14-…, Panopto cookies .ASPXAUTH + csrfToken + sandboxCookie
      get_delivery_info -> OK, duration 1115.354s, 2 streams
      Canvas cookies leaked to Panopto: NONE

  `discover_course_videos` already holds the module item id it needs. The
  generic `external_tools/retrieve?url=…` route also authenticates and lands on
  `Sessions/List.aspx` (the folder), which is what the legacy/folder path wants.
- **Attaching the Canvas credential to the Panopto `requests.Session` is SAFE
  and the existing comment is too strong.** "Mixing the two would send a Canvas
  login to a Panopto host" is true of a bare `cookies={…}` dict; a
  domain-scoped jar (`apply_to_requests_session`) is dropped by requests' own
  policy at the Panopto hop - measured above, `LEAKED: none`.
- Until this is built, a browser-mode user gets **no recordings, no transcripts,
  no subtitles**, reported as per-recording failures rather than as a reason.

## The credential census has a hole, and SEVEN sites fall in it
`test_no_engine_module_formats_its_own_bearer_header` bans a hand-written
`Bearer {…}`. It cannot see a site reverting to `cm.api_key`, which is `''` in
browser mode - the repo's own recurring shape. Eight such mutants were run
against `test_browser_login` + `test_panopto_auth_discovery` +
`test_panopto_institution` + `test_canvas_metadata_retry` +
`test_canvas_request_timeout`:

    SURVIVED  panopto/runner.py  discovery reverts to cm.api_key
    SURVIVED  panopto/runner.py  auth bootstrap
    SURVIVED  panopto/runner.py  per-task canvas_credential
    SURVIVED  panopto/stream.py  duration probe
    SURVIVED  sync/analysis.py   Panopto discovery
    SURVIVED  core/canvas_logic  per-worker module client from api_key
    SURVIVED  core/canvas_logic  page-metadata client from api_key
    CAUGHT    core/canvas_logic  download session built from a bearer   <- the only guarded one

The one that is caught is caught by the AST census on `ClientSession` kwargs.
**The fix is a census that fails on a NEW site passing `.api_key` into a
credential-consuming call** (`lti_launch`, `discover_course_videos`,
`_CanvasREST`, `_new_canvas_client`), not seven more assertions.

## The silent phase costs 13.7 seconds that nobody is waiting for
Measured in the real app against real CBS SSO, on a 4-core laptop:

    1.3s  notice "Checking your Canvas sign-in"
    3.3s  the hidden window is ALREADY on the CBS Entra login page
    17.0s the window is finally shown

`SILENT_TIMEOUT` is a CONSTANT, so a faster machine makes the dead time
**larger**, not smaller. It is paid by exactly the people who must type a
password: first run, and every re-login after the IdP session lapses.
- **Clicking "Sign in with Canvas" a second time destroys the open window.**
  `begin_browser_signin` calls `reset()` unconditionally. Measured: window gone
  at 2.5s, back at 17.6s, CBS login reloaded and anything typed lost. The window
  is not modal and has no owner, so ending up behind the main window - and
  clicking the button again - is the ordinary case, not an odd one.
- On Windows `show()` is `Show()` + `Activate()`, which under focus-stealing
  prevention may only flash the taskbar button; macOS calls
  `activateIgnoringOtherApps_`. So "the window appeared" is not "the user saw
  it", and the two platforms differ.

## A browser session that expires tells the user to paste a token
All four `force_reauth` call sites hard-code token wording
(`ui/course_selector.py:2271,2273`, `shared/components.py:226,228,1864`), and
the reconnect header adds *"Generate a fresh access token (guide below) and
paste it here - that's the only thing that changed."* At a school that has
turned token creation OFF - the population this feature exists for - that
instruction cannot be followed at all.
- Worse: `force_reauth` DELETES the stored browser credential, so the hidden
  renewal that would have fixed the session in seconds cannot run.
- **`refresh_silently()` exists in `core/browser_login.py` and has NO CALLERS.**
  **SUPERSEDED 2026-09-12: it was DELETED.** See the retention pass at the end
  of this file - the live path is `browser_restore_pending`, and a second
  implementation of one decision was the whole problem with keeping it.
  It is the function this path wants.

## The persistent profile makes a wedged WebView2 fatal to the NEXT launch
Before this feature every launch got its own temp user-data folder, so a
leftover WebView2 could not touch the next start. Both windows now share one
folder. Simulated the documented MSIX shutdown hang (suspend the WebView2
processes, then kill the host) and launched again - twice, same result:

    control (no wedge)   second instance loads in 5.4s
    wedged orphan        45s wait, then WebView2 init FAILS
                         HRESULT 0x80004004 E_ABORT -> the app's window never loads

- **An ordinary hard kill is fine**: measured 0 surviving WebView2 processes
  after `Stop-Process` on the host, because the browser process watches the host
  handle. It needs the specific wedge.
- `core/health_log._reap_recorded_orphans` runs inside `_boot`, i.e. racing the
  main window's own WebView2 init - so it is not a reliable defence. Reaping
  BEFORE `webview.start()` is, and "a live msedgewebview2 whose `--user-data-dir`
  is OUR profile and whose host is gone" is proof of ownership on its own.
- `core/health_log._scan_children`'s docstring is now FALSE where it says
  pywebview "hands it a fresh temp folder every launch". The reaper still works
  (it compares the udd it recorded), only the reasoning is stale.

## A REAL credential does not fit Windows Credential Manager
Measured through the app's own writer with a real CBS session:

    payload 1,630 chars = 3,260 bytes     (CredWrite limit: 2,560)
    CredWrite -> error 1783 "The stub received bad data"
    stored instead in .token_fallback (DPAPI);  load-back usable, verify OK
    cookies: canvas_session 762 · cf_clearance 426 · _csrf_token 102 · log_session_id 32

So on Windows a browser login lives in a FILE, not the OS credential store, and
three statements are now untrue: this file's own "stored in the SAME OS
credential store as a token"; `docs/privacy.html` and `docs/index.html`, which
tell users their credential is in Credential Manager / Keychain; and the implied
parity with macOS, where `_save_fallback_token` is a deliberate no-op so a
Keychain refusal means signing in again every launch.
- **`canvas_session` ALONE authenticates** - measured 200 + the user's name with
  every other cookie dropped. Harvesting only the session cookie(s) puts the
  payload near 1,800 bytes, inside the limit and a smaller secret at rest.
- `.token_fallback` is **not gitignored**, and this feature makes it the primary
  store on Windows: a dev run writes a credential blob into the repo root.

## The poll verifies against Canvas up to ~1,200 times per sign-in
`_worker` harvests and calls `verify()` on every 0.5s poll while the window is
on the Canvas host. Measured: `GET /login/canvas` - the landing page at every
institution WITHOUT SSO - returns `Set-Cookie: canvas_session=…; httponly` to an
anonymous visitor, so `usable` is true and `verify()` fires every poll for up to
the 10-minute interactive window. Skip the check when the session cookie VALUE
is unchanged since the last failure; Canvas rotates it on login, so the
successful attempt still fires at once.

## macOS parity, read out of pywebview 6.1 - still UNVERIFIED on a Mac
- **`storage_path` is IGNORED on macOS.** `cocoa.py` always uses
  `WKWebsiteDataStore.defaultDataStore()`; only `private_mode` matters. So the
  `webview/` folder `start.py` creates is EMPTY there, the gitignore comment
  describing it as the profile is Windows-only, and the profile actually lives
  in `~/Library/WebKit/<bundle id>` / `~/Library/HTTPStorages/<bundle id>`.
- **`get_cookies()` filters by SUBSTRING of the URL the window was opened with**
  (`if domain not in self.url`), where the Windows backend scopes to the CURRENT
  url (`GetCookiesAsync(self.url)`). Same answer for Canvas; a sibling host whose
  domain is a substring of the login URL (e.g. `canvas.instructure.com` inside
  `cbscanvas.instructure.com/login`) would be included on macOS only.
- **`clear_cookies()` is fire-and-forget** (`AppHelper.callAfter`, completion
  handler ignored) and removes **all** website data types; Windows'
  `DeleteAllCookies()` is synchronous via `Invoke` and cookies only. Logout then
  immediate quit is verified on Windows (below) and CANNOT be verified from here.
- `create_window` from the worker thread is marshalled with `AppHelper.callAfter`,
  so the threading is sound on both platforms.

## Autofill: measured, and it is one flag on Windows
**SUPERSEDED 2026-09-12: that flag is now SET.** This entry recorded the
defaults and stopped there, and the sentence below ("the sign-in window never
offers to save a password and never fills one") described a real and costly
gap for two passes before anyone acted on it. See "The sign-in window must let
a PASSWORD MANAGER work" at the end of this file. Note also that the claim
"there is no right-click paste" was true and MISLEADING: Ctrl+V worked all
along, measured.
Read off the live `CoreWebView2.Settings`: `IsPasswordAutosaveEnabled = false`,
`IsGeneralAutofillEnabled = true`, `AreDefaultContextMenusEnabled = false`,
`AreBrowserAcceleratorKeysEnabled = false` (the last two follow pywebview's
debug flag). So the sign-in window never offers to save a password and never
fills one, there is no right-click paste, and no Back or reload. On Windows the
autosave flag is settable on the window's own `CoreWebView2`; on macOS WKWebView
has no equivalent for a non-browser app, and passkeys need entitlements an
ad-hoc-signed bundle cannot carry.

## Session auth drops the `verifier=` from Canvas file URLs
Canvas adds it only for token requests - a session request is `in_app`
(`lib/user_content/files_handler.rb:56`, `lib/api/v1/attachment.rb:110`, and
`files_controller.rb` passes `omit_verifier_in_app`). Measured: **0 of 5** file
URLs carried a verifier. Downloads are unaffected (the cookie authenticates the
first hop), but images and links inside EXPORTED HTML/Markdown pages now need
the reader to be logged into Canvas in whatever browser opens them, where the
token build embedded a capability URL that worked anywhere.

## Verified GOOD - do not re-measure
- **The cookie never leaves the Canvas host**, on a real 4-hop redirect chain:
  `cbscanvas.instructure.com` **cookies sent**, then
  `a11736-…canvas-user-content.com`, `inst-fs-dub-prod.inscloudgate.net` and
  `cdn.inst-fs-dub-prod.inscloudgate.net` all **NONE**. 10,973 bytes, size
  matched Canvas, valid xlsx.
- **A real course download works in browser mode**: course 48672 through the real
  `download_course_async`, 11 files + 1 link + manifest, 1.60 MB, 8.5s, zero
  error events.
- **The real app restores a stored browser session**: "Logged in as Birk", 14
  favourites, 0 `stException`.
- **Logout really logs out on Windows**: credential deleted from the store, and
  the WebView2 profile's cookies gone and STILL gone after a relaunch - 3/3
  trials quitting 0.2s after the wipe, so the lazy cookie flush does not undo it.
- **Canvas does NOT prefix session-authenticated JSON with `while(1);`** - the
  `render` override in `application_controller.rb` no longer adds one, and 5 live
  probes (both Accept headers) confirm it. Closed.
- **Neither `cf_clearance` nor the User-Agent is load-bearing**: the API answered
  200 with the python-requests UA and with `cf_clearance` removed.
- **No credential value reaches any log the app writes** - debug_log.txt,
  health.log, session_state.json and the downloaded folder all scanned for the
  real cookie values: none.
- Session cookies do NOT survive a WebView2 restart (measured); only persistent
  ones do. That is why the keyring copy, not the profile, is what carries a
  sign-in across launches - and why the IdP's persistent cookie is what makes a
  silent renewal possible.

## Smaller, but written down so nobody re-finds them
- **`test_the_course_cache_really_accepts_a_browser_credential` is VACUOUS.** It
  builds a local dict and never touches `core.course_cache`, though its docstring
  claims it drives "the real module rather than a re-implementation".
- **A UTF-8 BOM in the settings file silently discards every saved setting and
  the saved login** - `json.load` with `encoding='utf-8'` raises, and
  `restore_saved_session`'s handler logs and falls through to the login page.
  `utf-8-sig` reads both forms. Pre-existing; hit by accident here.
- **`aiohttp.CookieJar()` refuses cookies for an IP-address host** (unsafe=False)
  and `requests`' jar refuses them for a dotless host like `localhost`. A
  self-hosted Canvas reached by IP therefore downloads nothing in browser mode,
  silently; one reached at `localhost` fails the API calls instead.
- **A two-session hot loop is reachable in theory**: with
  `browser_login_pending` set and the job reset elsewhere, `_browser_login_poll`
  sees `idle`, calls `st.rerun(scope="app")`, and `adopt_pending_browser_login`
  returns on the `idle` branch WITHOUT clearing the flag. Needs two live
  sessions; reasoned, not reproduced.

## What was CHANGED on 2026-09-11, and how each fix was proven
Every one was verified against real CBS Canvas or by driving the real app, not
by the suite alone. Suite after: **4,564 passed** (2 pre-existing failures, both
`shutil.which("bash")` resolving to the uninstalled WSL stub), architecture audit
**0 violations**.

- **Panopto now takes the IN-APP launch** (`panopto/auth.in_app_launch_url`, used
  by `lti_launch` only when the credential is a browser session, so token mode is
  byte-for-byte unchanged). Measured on the real account: `lti_launch` -> session
  + `panopto_base` + the real delivery id, `get_delivery_info` OK (1115.354s, 2
  streams), and `discover_course_videos` **0 -> 36 recordings in 15s**.
  - The Canvas cookies ride on the PANOPTO session's jar, and all three exits were
    checked afterwards: `_cookie_header` (what ffmpeg gets) = `.ASPXAUTH`,
    `csrfToken`, `sandboxCookie`; what requests would send to Panopto = the same
    three; what it sends to Canvas still carries `canvas_session`. **No Canvas
    secret reaches Panopto**, because the jar is domain-scoped.
  - Only the cookies are copied, never the User-Agent - the handshake keeps the
    one it has always sent.
- **The window appears when the PAGE SETTLES** (`SETTLE_POLLS`, 4 polls of an
  unchanged URL), with `SILENT_TIMEOUT` kept as the backstop for a chain that
  never settles. Measured in the real app, same machine, same account:
  **17.0s -> 5.5s**, with the IdP page ready at 3.2s. The settle counter is read
  AFTER the harvest, so a silent renewal that works still returns first and can
  never be interrupted by a window.
- **A second click brings the open window forward** (`bring_to_front`) instead of
  resetting. Measured: before, the window vanished at 2.5s and returned at 17.6s
  with the CBS login reloaded; after, it stays put and the page is untouched.
- **Only the session cookie is harvested.** A real CBS credential was 1,630 chars
  = 3,260 bytes against Credential Manager's 2,560; keeping `canvas_session`
  alone puts it inside the limit. `.token_fallback` is now gitignored either way.
- **An expired browser session is RENEWED, not destroyed.** `force_reauth` keeps
  the credential in browser mode and arms the same hidden renewal the startup
  path uses (armed, never awaited - `refresh_silently` blocks up to 40s and this
  runs on the script thread). The reconnect copy is chosen by credential kind, so
  a browser user is told to press "Sign in with Canvas" rather than to generate a
  token they may not be allowed to create.
- **A wedged WebView2 is reaped BEFORE `webview.start()`**
  (`core.health_log.reap_webview_orphans`). Verified both directions on real
  processes: a wedged orphan is reaped and the next launch loads in **3.3s**
  (against 45s and an E_ABORT failure), while a LIVE second instance keeps all six
  of its processes.
  - **The first version reaped ZERO**, because WebView2 does not use the folder it
    is handed: it creates `<profile>\EBWebView` and passes THAT as
    `--user-data-dir`. Measured, not guessed - and there is a mutant for it.
- **The `.api_key` census now exists**
  (`test_no_site_authenticates_with_api_key_instead_of_the_credential`, with its
  own positive control), closing the seven sites that were pinned by nothing.
- **The vacuous `course_cache` test now drives the real module** through
  `cc._loader`, and asserts both halves: one fetch for a repeated credential, a
  second for a renewed session.
- Left alone deliberately: the exported-HTML verifier difference (Canvas-side,
  and downloads are unaffected), and `docs/index.html`, which is the product
  owner's copy - `docs/privacy.html` gained the browser-session entry instead.

### Coverage after the pass, and the gap the pass itself found
`tests/test_browser_login.py` (82) and `scripts/_mutate_browser_login.py`
(43 mutants) - **42/43 caught**, the survivor the documented `clear_session`
equivalent. Re-run the pass, not just the suite.

**The settle rule MASKED the original shipped bug, and only the mutation pass
could see that.** With the window now appearing when the page stops moving, the
old "an interactive sign-in starts on the LONG clock" mutant stopped failing
anything: every login that settles shows its window either way. The regression is
still real for a chain that NEVER settles, which is exactly what
`SILENT_TIMEOUT` is the backstop for - so the test that restores the guard drives
a churning IdP whose URL changes on every poll (`_ChurningIdP`). Verified both
directions on a copy: unmutated PASS, mutated CAUGHT. **A new fast path can
switch off an old guard without touching it.**

# The 2026-09-12 review: security, robustness, and token parity

A second pass the day after, asking three questions rather than hunting crashes.
Report: `tests/audit/SIGNIN_REVIEW_2026-09-12.html`. Suite after: **4,591 passed,
38 skipped, 0 failed**, architecture audit **0 violations**, mutation **50/51**
(the survivor the documented `clear_session` equivalent). The two `shutil.which
("bash")` failures recorded on 2026-09-11 did not reproduce; measured here,
`which` resolves to `C:\Program Files\Git\usr\bin\bash.EXE` and it runs (rc 0),
not to the WSL stub. That is a difference in this machine's PATH, not a fix.

## A STORAGE limit must not narrow the LIVE credential
The 2026-09-11 fix trimmed `_harvest` to `canvas_session` because a real CBS
credential was 3,260 bytes against `CredWrite`'s 2,560. The measurement is
right and reproduces exactly through the app's own serialiser; the placement
was wrong. **Trimming at the harvest also took the extras away from the live
session**, and one of them can be load-bearing: an institution behind a WAF
issues a clearance cookie (`cf_clearance`, 426 chars on the measured session),
and without it the first API call meets a challenge page - a 200 that is not
JSON, which `verify()` reports as *"Your Canvas session has expired"*. At an
institution that needs it, that is a login that can never succeed and never
says why.
- **The harvest is now WIDE and `to_storable()` is narrow.** Measured:
  full jar 3,260 bytes (REFUSED, error 1783), stored copy **2,018 bytes**
  (fits). The at-rest secret is unchanged, so nothing is given up.
- The old code comment proposed *"widen this allowlist"* as the fix. A per-WAF
  allowlist (`cf_clearance`, `_abck`, `incap_ses_*`, `aws-waf-token`, ...) is a
  list nobody can finish; the constraint belongs where the constraint is.
- A restored credential carries the session cookie alone. If that is ever not
  enough the request fails like any expired session and the silent renewal
  harvests a fresh complete jar, so it is **self-healing, not terminal**.
- Consequence for the website: `docs/privacy.html` said the credential is
  *"usually too large for Credential Manager"*. That stopped being true on
  2026-09-11 and the page has been corrected.

## Widening the harvest is only safe with a DOMAIN check
pywebview's two backends scope `get_cookies()` differently, and the macOS one
is a plain **substring** test - `if domain not in self.url`, against the URL the
window was loaded with. On a window opened at
`https://cbscanvas.instructure.com/login`, a cookie for the unrelated tenant
`canvas.instructure.com` passes it, because that string occurs inside the URL.
Windows asks WebView2 for the current URL's cookies and is already correct.
- **This was already reachable for `canvas_session` itself** - the one cookie
  that decides the sign-in has finished - so the name allowlist was limiting
  the blast radius by accident, not by design.
- `core.canvas_auth.cookie_domain_matches` is the browser rule: exact host, or
  a real subdomain. **The dot boundary is load-bearing**: bare `endswith`
  makes `scanvas.instructure.com` a parent of `cbscanvas.instructure.com`.
- A morsel with **no** domain still passes: that is what a backend which
  already scoped its query returns, and `_FakeWindow` emits both shapes.
- Everything harvested goes into a jar scoped to OUR host, i.e. it becomes
  something the app SENDS to Canvas. That is why a foreign cookie matters here
  and would not in a browser.

## The window must say WHERE IT IS
The address bar is the one thing an embedded web view takes away, and the chain
really does leave Canvas (CBS -> `login.microsoftonline.com` -> back). A student
was typing a university password into a window with no URL anywhere on it. The
title now carries the current origin and follows the chain.
- **Punycoded.** `urlparse().hostname` returns the Unicode form, which is the
  form homoglyphs exploit; a Cyrillic `а` now renders `xn--pple-43d.com`.
- **`_set_title` must not block.** pywebview's title setter opens with
  `events.loaded.wait(15)` and this runs inside the 0.5s poll loop that owns the
  harvest, the settle counter and the cancel check. It checks `is_set()` first.
  `loaded` is cleared only by `load_url`/`load_html`, never by the redirect
  chain, so once the first page is in it stays set.
- **Track the title LAST APPLIED, not the previous URL.** The ordinary way the
  window appears is the settle rule - four polls of an *unchanged* URL - so
  "has the URL changed since last poll?" is false on exactly the poll after it
  is first shown, and a URL-diff indicator never appears on the common path.
- **The test for a STALL must watch for progress that does not arrive.** The
  first version asserted `not window.titles` after the attempt reported
  `needs_user`, which it does *before* the retitle - so it ran while the mutated
  worker was still asleep inside `wait()`, found an empty list, and passed. The
  mutation pass is what caught it (SURVIVED). It now counts polls: with the
  guard ~20 per second, mutated **1**.

## Smaller, and each one now has a mutant
- **`idle` + `browser_login_pending` is a LOOP, not a wait.** Recorded
  2026-09-11 as reasoned-not-reproduced; it is plain control flow.
  `_browser_login_poll` treats `idle` as terminal and reruns,
  `adopt_pending_browser_login` returned on `idle` without clearing the flag.
  Now terminal there too, and **silently** - `idle` is the absence of an
  attempt, and `was_interactive()` cannot speak for a job that no longer
  exists. Its test DRIVES the function; the old shape passes every structural
  assertion in that file.
- **`begin_login` orphaned the window of the job it superseded.** `_finish`
  declines to record a state for a job that is not current, so the old worker
  never reached the branch that closes one and a visible window sat there for
  its own full ten minutes. `ui/auth.begin_browser_signin` calls `reset()`
  first and so covered the app's own route, which is why it never showed up.
- **A UTF-8 BOM did not merely discard the settings, it QUARANTINED them.**
  `read_json_for_update` reads `utf-8`, a BOM raises `JSONDecodeError`, and
  that lands in the corruption branch - so an intact file is moved to
  `*.corrupt.json` and replaced, taking `auth_method` (hence the saved browser
  sign-in), the Canvas address, the accepted Panopto notice and the download
  defaults. Notepad and a PowerShell `>` redirect both write a BOM. Fixed with
  `utf-8-sig` at **all 12 JSON read sites**; writes stay `utf-8`, pinned by its
  own test so nothing starts emitting one. Mutation-checked both directions.
- **TLS validation is pinned by a census, and there is no live defect.**
  `webview.settings['IGNORE_SSL_ERRORS']` is False and `start.py` passes no
  `ssl=`, so certificates ARE validated. It is written down because pywebview
  registers `ServerCertificateErrorDetected -> AlwaysAllow` on either flag and
  **both are process-global** - the same hazard already recorded for
  `private_mode`, with a worse consequence: it would switch validation off in
  the sign-in window, not just the localhost one.

## Parity with the token path: two real gaps, both bounded
Everything below the auth layer is genuinely shared, and Panopto - yesterday's
blocker - now works. What is NOT 1:1:
- **`verifier=` on file URLs inside EXPORTED pages.** Canvas adds it only for
  token requests. Downloads are unaffected (the cookie authenticates the first
  hop); images and links inside an exported HTML/Markdown page need the reader
  logged into Canvas in whatever browser opens them. Canvas-side, left alone.
- **Credential LIFETIME.** `canvas_session` is `path=/; secure; httponly;
  samesite=none` with **no Expires**. **The rest of what this entry said was
  WRONG and is corrected below** ("How long a browser sign-in lasts"): the
  no-rotation measurement was taken anonymously, i.e. on an EMPTY session,
  which is the one case Rack's re-issue rule excludes. Canvas rolls an
  authenticated session cookie forward on every response, and the app now
  adopts it.
- ~~Google-SSO institutions remain unserved~~ - disproved on Windows, below.

## Open, and deliberately NOT guessed at
- **Signing out of the app does not sign you out of Canvas.** Logout deletes
  the stored credential and wipes the web view profile (verified on Windows);
  the harvested `canvas_session` stays valid on Canvas' side until it expires.
  A user can revoke an access token from their Canvas settings; there is no
  equivalent gesture for a harvested session. **Not fixed because it cannot be
  measured from here**: Canvas' logout is a POST/DELETE needing `_csrf_token`
  echoed as a header, and whether that invalidates an already-captured cookie
  depends on how Instructure configures its session store. Driving it needs a
  live authenticated session. Do not write a fix on reasoning alone.
- **`refresh_silently()` STILL has no callers** (re-checked 2026-09-12).
  **RESOLVED the same day by DELETING it**, not by wiring it up. The
  renewal that shipped goes through `begin_browser_signin(interactive=False)`
  from the login page, which is correct - it must not block the script thread.
  It is the natural implementation for a MID-RUN renewal, which is the one
  place a session is meaningfully weaker than a token: a session that lapses
  during a long download ends the run. Wire it there or delete it.
- **A self-hosted Canvas reached by IP downloads nothing, silently**
  (`aiohttp.CookieJar` refuses cookies for an IP host unless `unsafe=True`;
  `requests` refuses a dotless host like `localhost`). Unchanged, niche, and
  the fix is narrow - but it should be a decision, not a discovery.

## The FULL suite found the one defect the targeted run could not
`tests/test_browser_login.py` was green at 101 and the mutation pass was done;
the full suite then failed on `tests/test_unbound_names.py`. **The hit was in a
guard, not in the product** - and it was a false alarm, in a file whose
docstring promises it never produces one.
- **A decorator is evaluated in the scope the `def` SITS IN, not in the
  function's own scope.** `_loaded_names` walked `ast.iter_child_nodes` of the
  `FunctionDef`, which includes `decorator_list`, so `@title.setter` was
  checked against the method's scope - where `title` is of course not bound.
  The class body binds it two lines above, and a method never sees class-body
  names, which is exactly the rule that file gets right everywhere else.
- The first `@property` / `@x.setter` pair in this repo's history was written
  this session (in the test fakes). A guard is only exercised by the shapes
  somebody actually writes.
- **The first fix reported ELEVEN new false alarms**, all comprehension
  variables inside `@pytest.mark.parametrize` arguments: `_decorator_loads`
  used `ast.walk`, which descends into comprehensions and lambdas - their own
  scopes, binding their own targets. The same skip list the rest of the file
  uses fixes it.
- Decorators are now checked against the enclosing body's names, with a class
  body passing its OWN bindings down (`here=`). Deliberately the whole class
  body rather than only names bound above the decorator: that can suppress an
  alarm but never invent one, and this file's contract is that it never
  false-alarms. Two controls added, so the fix cannot have blinded it - an
  unbound decorator at module level and one inside a class are both still
  caught.

# The 2026-09-12 institution-support and session-lifetime pass

## GOOGLE IS NOT BLOCKED ON WINDOWS - the entry above was wrong
This file said *"Google is the exception: it blocks OAuth sign-in in embedded
webviews and names `WKWebView` explicitly, so institutions using Google as their
Canvas auth provider are the one population this route cannot serve."* **That is
false on Windows, and it was reasoned from Google's policy text rather than
measured.** Driven through the app's own web view, 2026-09-12:

    navigator.userAgent  Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...
                         Chrome/152.0.0.0 Safari/537.36 Edg/152.0.0.0
    accounts.google.com/ServiceLogin        -> the REAL sign-in form rendered
    accounts.google.com/o/oauth2/auth       -> 401 invalid_client

- WebView2's User-Agent is **indistinguishable from real Edge** - no `wv`
  marker, no embedded-webview token. Google's policy names
  `android.webkit.WebView` and `WKWebView`; WebView2 on the desktop is not
  named and is not detected.
- **The OAuth endpoint reached CLIENT VALIDATION**, failing only on the
  deliberately bogus `client_id` in the probe. `disallowed_useragent` is a 403
  raised BEFORE that, so getting `invalid_client` is positive proof the
  user-agent gate was passed.
- So every Google-SSO institution is served on Windows with **no code change** -
  the population this file described as unservable was never unservable here.
- **macOS is a different question and stays open**: `WKWebView` IS named by
  Google, and nothing here has been driven on a Mac. Do not assume it fails
  either - measure it.
- **Do NOT "fix" a macOS block by spoofing the User-Agent.** pywebview's
  `user_agent` is a `webview.start()` parameter, i.e. process-global like
  `private_mode` and `ssl`, so it would apply to the main window too - and it
  would be deliberate circumvention of a provider's security control. Detect
  and report instead.

## Canvas' auth providers, and which ones this route can serve
Read from `canvas-lms/app/models/authentication_provider/`: apple, canvas,
cas, clever, facebook, github, google, ldap, linkedin, microsoft,
open_id_connect, saml, plus the oauth/oauth2/delegated base classes. For
universities the live set is SAML (Shibboleth, ADFS, Entra), CAS, LDAP,
OpenID Connect, Microsoft and Google. All of them are ordinary web sign-in
flows in a browser, which is what this window is.

## THE ONE MEASURED GAP: an SSO popup goes to the user's REAL browser
`window.open()` during a sign-in chain does not land in the sign-in window. It
is handed to the system browser, whose cookie store this app can never read,
while the sign-in window sits on the page it was already on until the
ten-minute clock expires. **Nothing reports anything.** So an institution whose
identity provider uses a popup for any step cannot finish signing in.
- **Mechanism**: pywebview's `on_new_window_request` calls `webbrowser.open()`
  whenever `webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']` is true, and it
  is true by default. Measured with a local page calling `window.open()`: the
  sign-in window's URL did not change, its own server never saw the request,
  and **the product owner's screenshots showed the page open in Chrome.**
- **The global setting is NOT the fix.** It is process-global, and pywebview's
  handler navigates *the window whose handler fired* - so turning it off makes
  an external link clicked in the MAIN window navigate Streamlit away from
  localhost and take the running app with it. The login screen has such links.
- **AND THE PER-WINDOW HANDLER WAS BUILT, MEASURED, AND BACKED OUT. Read this
  before trying it again.** The chain is reachable
  (`window.native` -> WinForms `BrowserForm` -> `.browser` (pywebview
  `EdgeChrome`) -> `.webview` (the WebView2 control) -> `.CoreWebView2`), and
  two things bite in order:
  1. **`CoreWebView2` can only be touched from the UI thread** -
     `InvalidOperationException` anywhere else, and the login worker is a daemon
     thread. The first version caught that in its own broad handler and returned
     False, so it degraded silently and looked merely ineffective. Marshalling
     through `form.Invoke(Func[Boolean](...))` fixes that half.
  2. **`core.NewWindowRequested -= existing` IS A SILENT NO-OP.** pythonnet
     wraps a Python callable in a NEW delegate each time it is referenced, and
     `-=` removes only the delegate instance that was added. So pywebview's
     handler stayed subscribed, BOTH handlers ran, and the popup went to Chrome
     exactly as before - while the install reported success.
- **The probe said `handler_installed: true` and the fix did not work**, which
  is the transferable lesson: it measured that OUR subscription took, never that
  theirs had gone. A guard that cannot say no. The screenshots settled it, not
  the probe - two tabs, one per probe run, both in Chrome.
- **Options, none of them tried**: patch `webbrowser.open` for the duration of a
  sign-in (a global stdlib monkeypatch, reversible, makes our handler the only
  effective one); ask pywebview for a per-window setting; or detect a popup
  having been sent away and TELL the user rather than timing out silently. The
  last is the smallest and is worth having regardless of the others.

# How long a browser sign-in lasts: it is ONE DAY, rolling

Not 60/90/120 days. A Canvas session is a **day**, and the numbers are Canvas'
own: `config/initializers/session_store.rb` sets `expire_after: 1.day` and
`config/session_store.yml.example` documents it as `86400 # 1 day in seconds`.
Consul can override it, so treat one day as the documented default rather than a
guarantee.

- **It ROLLS, and that is what makes the feature usable.** Rack decides whether
  to re-issue a session cookie in `commit_session?` -> `forced_session_update?`,
  and `force_options?` lists `:expire_after` - so with that option set, any
  response for a **non-empty** session re-sends the cookie with a fresh day on
  it. Read from `rack-session` master, 2026-09-12.
- **CORRECTION to the 2026-09-12 review, which said the opposite.** That entry
  reported *"Canvas does not re-issue it on ordinary reads (4 consecutive
  requests, one Set-Cookie)"* and concluded the lifetime was absolute from
  login. The measurement was real and the conclusion was wrong: it was taken
  **anonymously**, and an anonymous session is EMPTY, which is exactly the case
  `!session.empty?` excludes. **An unauthenticated probe cannot answer a
  question about authenticated session handling.**
- **The app now carries the refresh back to the credential store**
  (`CanvasManager.refreshed_credential()`, adopted in
  `_adopt_restored_credential`). The live `requests`/`aiohttp` jars absorbed the
  rolled cookie all along and were then thrown away, so the stored copy stayed
  frozen at whatever was harvested on the day the user signed in - and expired a
  day later however much they used the app. It is now "a day after you last used
  it", which for anyone opening the app weekly is the difference between a hidden
  renewal on every launch and none at all.
- **It costs nothing if the premise is ever wrong**: an unchanged cookie answers
  `None` and nothing is written. That is also why this was safe to ship without
  a live authenticated measurement.
- **Canvas also has a "stay logged in" token.** **THE NUMBER BELOW IS WRONG
  and is corrected in the retention pass at the end of this file: the cookie
  is `remember_me_for 2.weeks`, and `expire_remember_me_after` is a different
  option on the session store. It also ROLLS (used, destroyed, re-issued), and
  only the native login form ever sets it - never SAML, OIDC or CAS.**
  The original entry, kept for its reasoning about a COPY:
- **Canvas also has a 30-day "stay logged in" token** -
  `expire_remember_me_after: 2592000` - but it is **one-time-use**: Canvas
  replaced the old authlogic persistence_token precisely because a stolen one
  was valid for a long time, so `pseudonym_credentials` is consumed on first use
  and replaced. Persisting it WITHOUT adopting every replacement would be worse
  than not having it: our copy and the web view profile's copy are the same
  token, whichever is used first kills the other, and the user is logged out of
  both. It is also typically absent at an SSO institution, where the IdP's own
  session is the long-lived thing. Do not reach for it before the rolling
  refresh above is proven in the field.

# An expired session does NOT 401 outside the API - and that was silent corruption

Measured against real Canvas, no credential at all, 2026-09-12:

| request | revoked TOKEN | expired SESSION |
|---|---|---|
| `/api/v1/users/self` | 401 JSON | 401 JSON |
| `/api/v1/courses/<id>/files` | 401 JSON | 401 JSON |
| `/courses/<id>/files/<id>/download` | **401** | **302 -> /login** |
| `/courses/<id>/modules/items/<id>` | 302 -> /login | 302 -> /login |

**The API is at parity and needed nothing** - canvasapi raises `Unauthorized`
for both and `is_auth_error` already routes it. Everything outside the API was
not. Follow that 302 - which every HTTP client does by default - and the chain
ends at the institution's identity provider answering **HTTP 200 with 45,524
bytes of HTML login page**.

- **What the download engine did with that**: its Content-Type guard caught the
  common case and reported *"Content-Type mismatch: server returned 'text/html'
  ... This usually means Canvas returned an error page."* That names Canvas as
  the culprit, matches none of `is_auth_error`'s keywords, and so **never
  routed to reconnect** - every remaining file in the course failed with a
  message the user can do nothing about. In token mode the same moment is a
  clean 401 and the reconnect flow fires.
- **TWO HOLES let the login page reach DISK.** The guard was
  `is_html_response and not expects_html and file_size_bytes > 0`:
  Canvas reports no size for some files, so a `0` there **skipped the guard
  entirely** for exactly those; and a file that legitimately IS `.html` set
  `expects_html`, skipping it too. Both now covered, because the login-redirect
  check runs FIRST and is type-independent.
- **`core.canvas_auth.is_login_redirect(visited_urls)` is the one definition**,
  and it reads the redirect CHAIN rather than the final response: a legitimate
  Canvas file download is also a redirect (onto the content CDN) and also ends
  200. Only the unauthenticated one passes through `/login`.
  - Matched on **PATH alone, deliberately**. A vanity address can land the chain
    on the canonical host, so requiring the host to match the one we hold would
    answer False in exactly the configuration it exists for.
  - The **dot boundary matters**: a bare `in` makes a file called
    `login_form.docx` read as a sign-in page and throws away a real download.
  - `visited_urls(response)` reads `.history` + `.url`, which `aiohttp` and
    `requests` both expose, so ONE reader serves both clients.
- **`CanvasSessionExpired` carries `status_code = 401`**, so `is_auth_error`
  recognises it through the one branch of that function which is not a substring
  search. A distinct type rather than a crafted message, because the alternative
  is every raiser remembering to spell a word the matcher happens to accept.
- **Not retried**, for the same reason the TLS failure beside it is not: the
  credential cannot change between attempts, so retrying spends the whole
  backoff schedule to fail three more times.
- **Panopto had the same shape and a worse symptom.** The in-app launch starts
  at a Canvas module-item page, which 302s to `/login`; the form-chain walker
  would then try to submit the IdP's sign-in form, exhaust its ten steps and
  report no delivery id - i.e. **"this course has no recordings"**, which is the
  wrong answer to "you are signed out" and the only one a user would ever see.
- Coverage: `tests/test_session_expiry.py` (26) and
  `scripts/_mutate_session_expiry.py` - **14/14 caught**. Everything is driven
  against a real local HTTP server that redirects the way Canvas does; no mocks,
  no network, no credentials.
  - **The Panopto test had to be DRIVEN, and the mutation pass is what proved
    it.** The first version asserted the source contained `is_login_redirect`
    and `CanvasSessionExpired` - which a mutant replacing the condition with
    `if False:` satisfies perfectly, and it duly SURVIVED. It now calls
    `lti_launch` against the fake Canvas and asserts it raises.
  - **A character-window anchor was replaced by an AST one** for the
    no-retry test, for the reason this repo has been bitten by twice: a comment
    explaining the fix pushes the code out of the window and the guard then
    passes against a regression. Note `ast.walk` flattens EVERY handler in the
    function, including the inner `.part`-write and manifest-record try blocks -
    compare handlers of the SAME `Try` or the ordering assertion fails against
    correct code.

## Two techniques worth reusing
- **Drive the REAL app window with no code change**: set
  `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333` before
  launching `start.py`, then `playwright.chromium.connect_over_cdp`. The
  sign-in window shows up as a second page, so its URL and a screenshot are
  available too - that is how the 3.3s/17.0s timing above was taken. Pair it
  with `CANVAS_DL_CONFIG_DIR` and a credential written through
  `store_browser_credential` to reach the signed-in app without a token.
- **Prove your probe can say YES before believing a NO.** The first logout
  measurement reported the IdP's cookies surviving a wipe. They did not: the
  fake IdP set its cookies on every path, so the browser's own `/favicon.ico`
  request re-set them each time the probe looked. A second probe with a positive
  control (seed 4 cookies, see 4) showed the wipe was complete. Same family as
  the `pgrep -f` self-match already recorded in `macos.md`.

# The 2026-09-12 RETENTION pass: how to make the user log in as rarely as possible

The product owner's framing, and it is the right one to keep: *"a login screen on
every launch is exactly the friction that will make users open the app once, log
in, try it, close it for the day, open it next day and see the login screen and
then close the app to go to canvas and never open the app again. It KILLS user
retention."*

Everything below is ordered by how much it actually buys, which is NOT the order
it looks like from the code.

## THE MEASUREMENT EVERYTHING RESTS ON: the profile keeps DATED cookies only

Driven twice, as two separate app launches against one local server, with the
WebView2 browser process proven gone in between (it outlives the python process
that hosted it, and a second launch on the same folder ATTACHES to it - which
would make a session cookie look persistent).

| cookie shape | same profile | different profile | private mode |
|---|---|---|---|
| `Max-Age=604800` plain | **survives** | no | no |
| `Max-Age=604800; Secure; HttpOnly; SameSite=None` | **survives** | no | no |
| no `Expires` at all (`canvas_session`'s shape) | **LOST** | no | no |

Both controls fail correctly, which is the only reason the yes means anything.

**Consequences, and they decide the whole design:**
- `canvas_session` has no `Expires`, so the profile NEVER carries a Canvas
  session across a launch. The copy in Credential Manager is the only thing that
  does, which is why `to_storable()` exists and why the rolling refresh matters.
- An identity provider cookie survives **iff it is dated**, and what dates it is
  the user ticking **"Stay signed in"** (Entra's KMSI sets `ESTSAUTHPERSISTENT`;
  without it `ESTSAUTH` is a session cookie). So for an SSO institution that one
  tick is the difference between renewing silently for weeks and a fresh login
  on every launch. Nothing the app can do from its side substitutes for it, and
  answering a security prompt on the user's behalf is not ours to do - so the
  sign-in notice ASKS. That sentence is the highest-leverage copy in the feature.
- Canvas' own remember-me cookie is dated, so it survives too (see below).

### TAKE TWO OF THAT PROBE WAS WORTHLESS AND SAID SO - the favicon
The first controlled run reported survival in **all three** modes, including two
controls that must fail. Cause: WebView2 requests `/favicon.ico` right after the
page, that request carries the cookies just set, and the probe's "anything that
is not /set is the second visit" rule logged it as the second visit. So the yes
came from run one every time.
- **Match the exact path and log every request with its path.** The fix was not
  a better inference, it was removing the inference.
- This is the third entry in this repo's history where a diagnostic could only
  say yes. Prove it can say no, with a control that must fail.

## Canvas' remember-me: 2 WEEKS, rolling, and NATIVE LOGIN FORM ONLY

Read out of Canvas' source 2026-09-12. **This corrects the earlier entry in this
file, which said 30 days and implied it was not worth reaching for.**

- `app/models/pseudonym_session.rb`: `remember_me_for 2.weeks`. The
  `expire_remember_me_after: 2592000` (30 days) quoted earlier is a DIFFERENT
  option, on the session store, not the cookie's life.
- **It rolls.** `persist_by_cookie` does `token.use!` (which destroys the row),
  then on success sets `self.remember_me = true` and calls `save!` - and
  `save_cookie` generates a fresh `SessionPersistenceToken` and writes a new
  cookie. So one-time-use, and replaced on use. The earlier entry's warning that
  persisting our own copy would kill the browser's is still right for a COPY;
  it does not apply to the single copy living in the web view profile.
- **Only `Login::CanvasController` ever sets it** (`params[:pseudonym_session]
  [:remember_me]`). Grepped: SAML, OpenID Connect and CAS never do. So it helps
  Canvas-native and LDAP institutions (LDAP goes through the same form) and does
  **nothing** for most universities.
- **We therefore store nothing extra for it.** The profile holds it natively,
  dated, and the silent renewal uses it by simply navigating to `/login`. One
  copy, so the one-time-use hazard cannot arise.

## THE UPGRADE THAT ACTUALLY SOLVES IT: mint a real access token

`core/token_mint.py`. A session is a DAY; a token a student mints for themselves
is up to **120 days**, and it renews itself off its own value.

- `POST /api/v1/users/self/tokens` is a **documented** Canvas API
  (`@API Create an access token`). `token[purpose]` required; for a user whose
  roles are only student and/or observer an expiry is REQUIRED and capped at
  `TokensController::MAXIMUM_EXPIRATION_DURATION = 120.days`.
- **We ask for 119, and the missing day is the point.** Canvas compares
  `expiration_date > 120.days.from_now` against ITS clock, so a laptop a few
  minutes fast asks for more than the cap and is refused outright. A mutant
  raising it to 120 is caught.
- **It is strictly better than the session it replaces, three ways at once**: it
  lasts 120x longer; it is **revocable and visible** to the user under Canvas ->
  Account -> Settings -> Approved Integrations, which closes the one security
  gap the 2026-09-12 review could only state; and it has full parity, because
  Panopto needs a token to mint an LTI launch and session auth drops the
  `verifier=` from file URLs in exported pages.

### ...and it is BLOCKED at the institutions this whole feature exists for
Three account settings switch self-service tokens off, from `AccessToken`'s
policy: `limit_personal_access_tokens`,
`restrict_personal_access_tokens_from_students` (aimed exactly at our users) and
the `can_manage_own_access_tokens?` gate.

**CBS has it off.** Stated by the product owner 2026-09-12: *"what the login with
canvas feature with the cookie auth was made for, was for all the students whose
administrators switched off the generation of an access token - which is an
increasing amount by now."* So the mint is an **upgrade for the schools that
allow it and never a requirement**. Every failure path leaves the caller holding
exactly the session it came in with, and `token_upgrade_blocked` is recorded so
a student at a restricted school is not asked again on every sign-in.

### Four things about this that are easy to get wrong
- **CSRF applies.** `ApplicationController` has `protect_from_forgery with:
  :exception` and a cookie-authenticated request is in-app, unlike a Bearer one
  which skips it. Canvas' own client echoes the `_csrf_token` cookie in
  `X-CSRF-Token` after `decodeURIComponent` - the cookie is base64, so it is
  percent-encoded, and sending the raw value fails the check. We
  `urllib.parse.unquote` it. **The token is fetched from Canvas** (one GET of
  `/profile/settings`) rather than read from the credential, because
  `to_storable` narrows the STORED credential to the session cookies, so a
  restored one has no CSRF token at all.
- **A remembered session may not mint.** `require_password_session` rejects any
  session established from a `pseudonym_credentials` cookie, and it is a
  `before_action` on `TokensController` - so the redirect happens on the POST.
  **Following that redirect ends on the sign-in page answering 200**, so a
  classifier gated on the status alone never runs: the code fell through to the
  JSON parse and reported "Canvas returned no token value" about an entirely
  ordinary remembered session. Found by the mutation pass, not by reading, and
  it was a real defect and not only a gap in the tests.
- **The renewal EXTENDS, it never regenerates.** `token[regenerate]` replaces
  the token VALUE, and the value is what the running session, every download
  thread, the sync executor and the Panopto runner are already holding - so a
  renewal meant to save a login in three months would log the user out of their
  own running app, mid-download. `PUT` with only `expires_at` runs Canvas'
  `update` action and keeps the value, which is also what lets the renewal run
  on a background thread at all. An extension Canvas ACCEPTS but does not APPLY
  is deliberately not reported as renewed, or it would retry on every launch for
  the rest of the token's life.
- **A token must never mint a FIRST token.** `AccessToken`'s policy reads the
  account restrictions out of `session[:root_account]`, which a Bearer request
  does not have (Canvas' own comment: *"if the session wasn't set up correctly,
  just ignore the additional restrictions"*). So minting with a token would
  appear to work at an institution that deliberately switched them off.
  Extending something an administrator already allowed is fair use of that;
  minting is not. `mint()` refuses a token credential and a mutant removing that
  refusal is caught.

### The census caught MY OWN code, which is what it is for
`test_no_engine_module_formats_its_own_bearer_header` failed on
`core/token_mint.py` formatting a Bearer header itself in `extend()`.
`canvas_auth` is the one place that header is written, and the rule is not
cosmetic: that method is also where *"browser mode sends NO Authorization
header"* lives, so a hand-rolled header is a site that cannot inherit a later
correction to either rule. `extend()` now asks
`from_token(token).auth_headers()`.

## The startup dead-end, which was the visible half of the complaint

`refresh_silently()` had NO CALLERS for a third pass running and is now
**deleted**: the live path is `browser_restore_pending` -> the login page calling
`begin_browser_signin`, and a second implementation of one decision is the
`make_long_path` shape.

- **The renewal at startup is now `interactive=True`.** Both modes start the
  window HIDDEN on the same short clock, so the silent attempt is identical
  either way; only the failure differs. A non-interactive job gave up and
  reported *"Your Canvas session could not be renewed"*, which lands the user on
  a login form holding a live SSO session that one click would have spent.
  Interactive shows the window it already has open, which is what a browser does
  when you visit Canvas signed out. Chosen by the product owner 2026-09-12.

## The settings marker is a HINT; the credential store is the FACT

`restore_saved_session` only looked for a stored browser session when
`config['auth_method'] == BROWSER`. `_persist_browser_login` writes the session
FIRST and the marker second, and the marker write is allowed to be skipped (an
intact config file that cannot be read is never overwritten) - so a sign-in can
legitimately end up stored with nothing naming it, and that user gets **a login
screen every single day with a perfectly good session in Credential Manager**.
- `_restore_browser_session(api_url)` is now ONE implementation with TWO call
  sites: the marker, and a last-resort attempt when no token was found. Additive
  by construction, which is what makes widening it safe - it runs only when no
  token was found AND nothing has signed in yet, so it can never preempt a
  working token.
- A test counts the call sites and fails if `restore_saved_session` arms the flag
  itself again.

### The old test for this went stale and read exactly like a missing guard
`test_no_stored_session_never_triggers_a_hidden_renewal` asserted the flag write
sat inside an `if _saved_cred is not None:` branch **of
`restore_saved_session`**. Extracting the decision made it fail with *"no longer
arms a renewal at all"* against code that arms it correctly. It is now DRIVEN
with a fake store, and it has a positive control (a stored session Canvas refuses
DOES arm a renewal) without which it proves nothing. Fourth instance of this trap
in this repo; the `_mutate_browser_login.py` anchor for the same property had to
be re-anchored in the same commit, which `tests/test_mutation_anchors.py` caught.

## Considered and NOT done, with the reason

- **Persisting session cookies via a Chromium `--restore-last-session` switch.**
  Would make the profile keep `canvas_session` and an un-ticked `ESTSAUTH` across
  a launch. **Not done, and this is REASONING rather than measurement**: the gain
  is bounded by the SERVER-side expiry, which is one day for Canvas and about a
  day for a non-persistent Entra session, so it buys nothing the stored cookie
  does not already. Measuring the switch would have measured the wrong half.
- **Pre-ticking "Stay signed in" for the user**, by injecting JS into the
  institution's login form. It is their security decision and not ours to
  answer, and it depends on the IdP's CSP. We ask instead.
- **Reading the real browser's cookie store.** Still closed, for the reasons in
  the section at the top of this file, and now also unnecessary: the app can hold
  its own credential with the same lifetime the browser has.
- **Persisting the IdP's cookies ourselves** - **DONE 2026-09-12, and it did
  NOT need the DPAPI file this entry imagined.** See "THE STRAIGHT PATH" at
  the end of this file: re-dating the cookie inside WebView2's own store is
  enough, so nothing is harvested and no new credential store exists. The
  original note, kept because its caution about the interop was right:
- **Persisting the IdP's cookies ourselves** into a DPAPI file and re-injecting
  them with `CoreWebView2.CookieManager`. It is the "maximum effort" answer for
  an un-ticked KMSI, and it is the same UI-thread pythonnet interop that the
  popup fix already failed at once. Not attempted; recorded as the next idea if
  the ask returns.

## Coverage

- `tests/test_token_mint.py` (46), driving a REAL local HTTP server that answers
  the way Canvas' source says it does. No mocks, no network, no credentials.
- `scripts/_mutate_token_mint.py`: **25/25 caught**, after two survivors that
  were both genuine gaps in my own tests - a float bound that "less than
  MAXIMUM_DAYS" satisfied at 119.9999 days, and a login redirect served on the
  GET instead of the POST, which never exercised the classifier at all.
- **NOT YET VERIFIED AGAINST REAL CANVAS.** The mint has never been run against
  a live account: the product owner's token predates CBS switching token
  creation off and is not on this machine (57 Windows credentials, zero Canvas;
  no DPAPI fallback file anywhere). Everything degrades to the session on any
  failure, and every reason is logged distinctly, so the first real sign-in will
  say exactly what CBS answered. **That is the next thing to do.**

# The sign-in window must let a PASSWORD MANAGER work (2026-09-12)

**This is the friction a longer session does nothing about, and it is paid on
every sign-in rather than once.** The retention work above stretches the
interval between logins; this is about what each one costs. The product owner's
framing: students keep their institution login in their browser's password
manager and autofill it every time, *"and if we dont support this, its a major
friction point that we need to do everything to counteract."*

The app's web view is a separate profile that knows none of those saved
passwords, and WebView2 ships with the password manager OFF. So before this,
a student typed a full institutional password by hand, every time.

## What was measured, and the control that makes it mean anything

Read off the live `CoreWebView2.Settings` in a window built the way
`core/browser_login.py` builds one:

| setting | default | after `enable_password_manager` |
|---|---|---|
| `IsPasswordAutosaveEnabled` | False | **True** |
| `AreDefaultContextMenusEnabled` | False | **True** |
| `IsGeneralAutofillEnabled` | True | True (already on) |
| `AreBrowserAcceleratorKeysEnabled` | False | False (left alone) |

- **Ctrl+V ALREADY WORKED, and paste was never the blocker.** Measured by
  putting a known string on the clipboard, focusing a real `type=password`
  input and reading the value back out of the DOM: it pasted, with
  `AreBrowserAcceleratorKeysEnabled` still False. The **control** - the same
  probe with no keystroke sent - came back with an empty field, which is the
  only reason the yes is worth anything.
- **So the context menu is for DISCOVERABILITY, not capability.** A user who
  reaches for right-click, which is what a password-manager extension's users
  do, previously got nothing at all.
- `IsPasswordAutosaveEnabled` is the one flag that gates BOTH halves: WebView2's
  docs are explicit that with it False "no new password data is saved and no
  Save/Update prompts are displayed", while already-saved data is still
  auto-populated.

## THE READ-BACK IS THE DESIGN

`enable_password_manager` writes the two properties and then reads them off the
live object, and only answers True if the object agrees.

That is a direct consequence of the popup fix that was built and backed out on
2026-09-12: it reported `handler_installed: true` while plainly not working,
because it measured that OUR subscription took and never that pywebview's had
gone. **A guard that cannot say no.** A settings property CAN be read back, so
this one is not allowed to guess. A mutant replacing the read-back with
`return (True, True)` is caught, and so is one that reports success on a
refused write.

## EVERY CLR TOUCH GOES INSIDE THE UI-THREAD HOP - found by a HANG

`.CoreWebView2` is a WinForms control property and the sign-in worker is a
daemon thread, so reaching it from there is a cross-thread access.

- The first version of `_webview2_control` reached `.CoreWebView2` **itself**,
  outside any hop. The probe that exposed it did not fail, it **HUNG** - 24
  WebView2 processes alive, no output, killed from outside.
- **The two earlier probes that "proved the API works" had both happened to
  touch it inside `form.Invoke`.** So they were right about the API and silent
  about the threading, and the product code took the wrong lesson from them.
- Caught and turned into "not ready yet", that access would have made the retry
  answer False for ever and the feature **silently never activate** - the exact
  failure shape this file already records for the popup guard.
- `_webview2_control` now stops at the control (`window.native` -> `.browser`
  -> `.webview`, all plain Python attributes on pywebview's own objects, safe
  from any thread). `enable_password_manager` and
  `_clear_profile_identity_data` touch `.CoreWebView2` only inside the closure
  they hand to `_on_ui_thread`. An AST test asserts exactly that, in both
  directions.
- **A zero-sleep busy-wait on a CLR object starves the UI thread it is waiting
  for.** The probe's retry loop had no sleep, which is what wedged it. Poll
  politely.

## CORRECTED: there is no revert race, and the first explanation was invented

The call was first placed behind a "the window has reported a URL" gate, on the
reasoning that pywebview sets `AreDefaultContextMenusEnabled` itself inside
`on_webview_ready` and would silently revert an earlier write.

**Measured, and the hazard does not exist.** `CoreWebView2` is None until that
very event fires, and the write is marshalled onto the same UI thread, so it
cannot interleave with the handler - it can only be queued behind it. Raced as
hard as possible (an attempt every 20ms from window creation): first success at
**2.25s**, then 6 seconds of sampling with **no revert**, both values True
throughout.

- So the ordering is safe **by construction**, not by timing, and the gate was
  removed. It only delayed the setting past the first page load - which at a
  Canvas-native institution IS the password form.
- Recorded because it is a clean instance of this repo's own rule working
  against its author: a plausible mechanism was reasoned into a docstring, the
  measurement disproved it, and the real reason turned out to be stronger.

## LOGGING OUT MUST REACH THE SAVED PASSWORD - a requirement this feature CREATED

`clear_session()` called `clear_cookies()` only. Its own docstring reasons about
a shared machine - *"leaving it intact at logout would mean the next launch
signs straight back in, as the PREVIOUS user"* - and once the profile can hold
an institution password that stops being true: the next user finds it filled in
for them.

- `CoreWebView2.Profile.ClearBrowsingDataAsync` is the only API that reaches
  saved passwords. Measured available on the bundled runtime, along with
  `CoreWebView2BrowsingDataKinds.PasswordAutosave` as its own kind.
- **`Cookies | PasswordAutosave | GeneralAutofill`, deliberately NOT
  `AllProfile`.** The profile is shared with the app's own localhost window, and
  `AllProfile` also wipes caches and site storage belonging to it. Measured:
  the OR form clears (1 cookie -> 0), value 3136.
- **The returned Task is NOT awaited.** It completes on the UI thread's own
  message loop, so waiting on it from there deadlocks. `clear_cookies()` is
  still called as well, synchronously, so that "the cookies are gone" is true
  by the time `clear_session` returns - on the one store a caller can verify.
- **There is no API to enumerate saved passwords**, so "the passwords are gone"
  cannot be read back the way a settings property can. The honest proxy is that
  cookies ARE readable and the same call clears them. Stated rather than
  papered over, and a logout that could only clear cookies now WARNS - a
  destructive action that reports nothing is a bug waiting to be
  un-diagnosable, which is this file's own lesson from the marker force-close.

## Consequences elsewhere

- **`docs/privacy.html` carried a claim that was already wrong and would have
  become clearly wrong**: *"Your Canvas login password is never entered into or
  seen by the app"*. With browser login the user types it into a window the app
  hosts, and with this change the window can store it. Rewritten to say what
  actually happens: token means no password at all; sign-in means you type it
  into your university's real page, the app does not read it, the window may
  offer to remember it encrypted for your Windows account, and signing out
  deletes it.
- **macOS gets nothing here and says so.** WKWebView has no equivalent for a
  non-browser app and passkeys need entitlements an ad-hoc-signed bundle cannot
  carry. The function answers False off Windows without touching anything, and
  the test drives that branch from Windows by answering the platform guard - a
  `skipif` would only ever run on the rented machine, which is this file's
  existing rule.

## Coverage

- `tests/test_browser_login.py` grew to 112 (from 104): the write, a REFUSED
  write, an uninitialised web view, the off-Windows no-op, the UI-thread AST
  census in both directions, the `_worker` call-site census, the logout kinds,
  and the warning when only cookies could go.
- `scripts/_mutate_browser_login.py` gained 10 mutants for this.
- **NOT YET VERIFIED END TO END.** The flag write is measured; the round trip a
  student actually experiences - Canvas or the IdP offering "Save password?",
  accepting it, and the NEXT sign-in autofilling - needs one real sign-in,
  because nothing can click that prompt from a test. Same human pass that the
  access-token mint is waiting on.

# THE STRAIGHT PATH: the app's own "stay signed in" (2026-09-12)

The product owner's direction, and the segmentation is his: OAuth per
institution is **out**; a browser extension is **supplementary**; *"the
straight path is the session + saved password + idP cookies which majority of
users with access token generation disabled for their institution will use -
we need to build that."* Plus, for the other segment, *"the minted x-day token
(remember the expiry length differs from institution to institution)"*.

So there are three credentials, for three populations, and the straight path
is the one that has to work at a school like CBS where token creation is off.

## The measurement this rests on, and the control

The profile keeps cookies carrying an expiry and LOSES ones that do not
(measured earlier in this file, with two controls). So an identity provider the
student did not tick "Stay signed in" at leaves a **session** cookie, it is
gone on the next launch, and they sign in again. That tick box is the single
thing deciding whether the next launch renews silently.

`CoreWebView2.CookieManager` can enumerate the whole profile and write a cookie
back with an expiry, which is exactly what the tick box does - so the app can
provide one at **every** institution, including those whose IdP offers none.

**Measured end to end, two processes, with the browser process proven gone in
between:** a session cookie converted in run 1 came back in run 2 reading
`IsSession = False` and was sent to the server. **The control - a second
session cookie left untouched - did NOT come back.** Without that control,
"the cookie survived" could just mean the profile keeps session cookies by
itself, which would make the whole exercise pointless.

## Three things measured rather than guessed, each cost a run

* **`GetCookiesAsync(None)` returns the WHOLE profile**, not the current page's
  cookies. This is what makes the IdP reachable at all: pywebview's
  `get_cookies()` is scoped to the current URL, so a window sitting on Canvas
  can never see `login.microsoftonline.com`'s cookie. A mutant that filters
  the enumeration is caught.
* **The Task must be started on the UI thread and polled from the worker.**
  Waiting on it inside the hop deadlocks - it completes on that thread's own
  message loop.
* **`CoreWebView2Cookie.Expires` is a `System.DateTime`**, even though the
  underlying C++ API takes a double. Assigning a float raises *"'float' value
  cannot be converted to System.DateTime"* - **inside the UI-thread closure,
  where nothing surfaces it**, so the sign-in looks fine and is silently
  forgotten on the next launch. This is the failure mode to fear in this whole
  area: an exception in a closure marshalled to another thread is invisible
  unless something reads it back. A mutant restoring the float is caught, and
  a test asserts the value is not a float.

## What is NOT done here, deliberately

* **Nothing is extracted.** The cookie is re-dated INSIDE WebView2's own
  encrypted store: never read out, never written to a file of ours, never sent
  anywhere. That is what makes this materially different from harvesting an
  SSO cookie, and why it needs no new credential store - the option this file
  previously listed as "the maximum-effort answer" turned out not to be
  necessary.
* **An already-dated cookie is left alone.** Re-dating one the IdP gave a
  short life on purpose would be overriding its choice rather than standing in
  for a missing tick box.
* **`core` does not read the settings file.** The choice is made by
  `ui.auth._keep_signed_in_enabled()` and threaded through `begin_login` into
  `_Job`, so that store keeps exactly one reader - the co-ownership defect
  `.claude/rules/data-safety.md` records was four modules reading and writing
  one config. A test asserts `core/browser_login.py` never names the settings
  file.

## The security posture, stated rather than assumed

`keep_signed_in` defaults **ON**, because the user asked the app to sign them
in and the point of the feature is not to ask again. An unreadable settings
file also answers ON: the cost of being wrong is a sign-in that outlives the
app, which is what they chose, while the cost of defaulting OFF is the daily
login this exists to remove.

**What it means, honestly:** the profile can now hold a live identity-provider
session across restarts - and at an Entra tenant that session reaches every
Microsoft 365 service the student has, not only Canvas. Three things bound it,
and they are why this was judged acceptable rather than merely convenient:

1. It is WebView2's own DPAPI-encrypted store, per Windows user - the same
   protection Edge gives the same cookie.
2. The app never reads it. Only the sign-in window uses it, by navigating.
3. **Signing out clears it**, along with any saved password - see the logout
   entry above, which is a requirement the password manager created and this
   inherits.

**A UI toggle is still missing.** The setting is read and honoured; nothing
lets a user flip it without editing the settings file. Placing a control needs
a browser-verified pass (Streamlit reconciles by index), so it is stated here
rather than guessed at.

## The token for the OTHER segment: the grant differs by INSTITUTION

Corrected the same day, on the product owner's prompt. 120 days is only the
ceiling a student may ASK for: `AccessToken#set_permanent_expiration` takes the
real lifetime from `developer_key.tokens_expire_in`, and a site-admin cap can
shorten it further.

- **A fixed 21-day renewal window is wrong for every school granting less than
  21 days.** The token is "due for renewal" from the moment it is minted, so
  every launch spends a request, is capped straight back, and logs about an
  expiry that did not move. That is what shipped a few hours earlier.
- `renewal_threshold_days(granted)` is `min(RENEW_WITHIN_DAYS, granted/3)`. A
  third leaves two chances to succeed before expiry at any grant length, which
  matters because the app only gets to try when it is launched. A property
  test asserts a fresh grant of ANY length (1 to 365 days) is never
  immediately due.
- The granted lifetime is recorded as `minted_token_days` at mint time, since
  Canvas never tells you again.
- **`CAPPED` is its own reason**, neither success nor failure: the token still
  works, and the institution will not extend it. The caller records
  `minted_token_capped` and stops asking, because that answer cannot change
  between two launches.
- `token_source = 'minted'` is recorded so the reconnect screen can offer
  "Sign in with Canvas" rather than telling a user who never pasted a token to
  paste a new one. **The reconnect screen does not read it yet** - that is the
  next small piece.

## Coverage

- `tests/test_browser_login.py` 122, `tests/test_token_mint.py` 62.
- `scripts/_mutate_browser_login.py` and `scripts/_mutate_token_mint.py` both
  extended; see the session's final counts.
- **A test-process trap worth remembering**: `from System import ...` only
  works once `clr` has been imported, which pywebview does in the real app and
  a test process does not. The first version of the persistence helper left
  `System` out, so the closure raised `ModuleNotFoundError`, the count came
  back 0, and **the test failed against correct code**. Inject a fake `System`
  module, the same way the logout test fakes
  `Microsoft.Web.WebView2.Core`.
- **NOT VERIFIED END TO END.** The mechanism is measured against a local
  server; what is unverified is the thing that matters to a student - sign in
  at a real institution, close the app, open it a day later, and land signed
  in. That needs one real sign-in.

# The browser-extension handoff: the zero-typing route (2026-09-12)

`core/handoff.py`, `extension/`, `tests/test_handoff.py`,
`scripts/_mutate_handoff.py`.

**SUPPLEMENTARY, by the product owner's ruling**: *"We can build a browser
extension, but it HAS to be supplementary as an add-on choice for users who
don't want to keep logging in."* The in-app sign-in stays the straight path and
nobody has to install anything. So the card sits BELOW the sign-in button and
its copy says what it needs rather than selling it.

## Why it is not the thing this file's opening section rules out

That section closes reading cookies out of an installed browser's **files**:
Chrome's App-Bound Encryption killed it, and it is the technique credential
stealers use. This is the opposite. The browser hands the cookie over itself,
through its own extension API, because the person who owns it clicked a button.
No database is read, nothing is decrypted, and ABE is irrelevant because the
request comes from **inside** the browser.

The earlier wording - *"reading cookies out of an installed browser is dead,
and it is dead on both platforms at once"* - was a conclusion about a
TECHNIQUE that read as a conclusion about a GOAL, and it closed this route
conceptually for two passes. Worth remembering as a writing failure: state
what was measured (the file route is dead), not the category it belongs to.

## What it removes, which is more than a password

The student is already signed in to Canvas in Chrome, with their institution
password in Chrome's own password manager. The extension reports the HOST of
the tab it read - so **no institution is picked, no address typed and no
password entered**. All three already happened, in Chrome, for Canvas itself.
It is the only route in the app that asks for nothing at all; every other one
needs at least the Canvas address.

## The threat model, because a loopback listener deserves one

Five properties, and the shape of both halves follows from them. Each is driven
against the real server in `tests/test_handoff.py`.

1. **Loopback only.** Bound to `127.0.0.1`. A test connects to the machine's
   own routable address and requires a refusal - bound to `0.0.0.0` this would
   accept a Canvas session from anyone on the campus wifi.
2. **Time-boxed and user-initiated.** Opens when the user presses the button,
   closes on the first accepted handoff, times out after `WINDOW_SECONDS`
   (180). **Stopped by logout**, at the ONE place logout and `force_reauth`
   both go through (`_reset_browser_login_state`) rather than at each caller -
   a logout that leaves a socket accepting Canvas sessions is a logout in name
   only.
3. **EXTENSION ORIGINS ONLY, and this is the check the whole design rests on.**
   `Origin` is a forbidden header name, so a page's script cannot set it - the
   browser does. A page on the internet therefore cannot pretend to be
   `chrome-extension://`. That single `if` is what makes opening a port on the
   user's machine acceptable at all.
4. **Nothing readable by a page even if one did POST.** The CORS headers echo
   only an extension origin, so a page gets no body. Data flows ONE way: this
   endpoint never returns anything but an acknowledgement, so there is nothing
   to steal even in principle.
5. **The credential is proven and the user is NAMED.** It adopts through
   `_adopt_restored_credential`, the same door as a token and an in-app
   sign-in, which verifies against Canvas and then shows whose account it is.
   That is the residual risk and it is bounded to "somebody could sign you
   into an account that is not yours", which the screen then shows.

Only `canvas_session` / `_normandy_session` / `_csrf_token` are accepted, by
name, so a future version of the extension - or a bug in it - cannot widen what
the app stores just by sending more. A mutant removing that filter is caught.

## The extension asks for NO site access at install time

`optional_host_permissions` plus `chrome.permissions.request` at click time, so
Chrome's prompt names the one site the student is actually on. The alternative -
`host_permissions` in the manifest - means holding "read every site's cookies"
from the moment it is installed, for a tool used once a term. No content
script, no background worker, no `tabs` permission; `activeTab` gives the tab
the user invoked it on and nothing else. Tests assert all of it, including that
`host_permissions` is ABSENT.

## A MANIFEST THAT NAMES A MISSING FILE IS A DEAD EXTENSION

Shipped exactly that, and the product owner hit it before any test did. The
manifest declared `icon128.png`; nothing created it. Chrome answered *"Could
not load icon 'icon128.png' specified in 'icons'. Manifest could not be
loaded"* and **refused the entire extension** - not a missing icon, a feature
that does not install.

- Fixed by generating 16/32/48/128 from `assets/icon.png`, so the toolbar
  button is recognisably the same product, and by setting
  `action.default_icon` as well: without it Chrome draws a grey placeholder,
  which is not something anyone hunts for in a toolbar.
- **The durable artifact is the guard, not the icon.**
  `test_every_file_the_manifest_NAMES_actually_exists` walks icons,
  `default_icon`, the popup, the service worker, content scripts and
  web-accessible resources, plus one level down for `popup.html`'s own
  `<script src>`. It covers the next reference rather than that one file.
- The class is this repo's own: a reference to something that is not there,
  failing loudly somewhere nobody was looking. It is the extension-manifest
  cousin of "a documented test that was never committed measures nothing".

## Two traps worth keeping

**Three mutants reported as SURVIVORS and were ANCHOR failures.** Two `old`
texts matched twice (`cancel_browser_handoff()` and
`_adopt_restored_credential(credential)` appear in both the handoff and the
in-app path) and one matched nothing. An anchor that resolves twice takes
whichever is defined first; one that resolves zero times reports as a survivor
under a label that is a lie. `tests/test_mutation_anchors.py` catches the
zero case; only reading the count catches the double. **Check the ANCHOR
column before believing a survivor.**

**A structural guard should be stricter than the property, and this one was
right to be.** `test_the_signin_notice_emits_exactly_one_element_in_every_state`
counts `st.markdown` calls in the poll fragment's SOURCE. The first version of
the handoff branch added a second one in an exclusive branch that returned -
so exactly one ever executed, and the test failed anyway. It was correct to:
a second write in an exclusive branch is one refactor away from being
reachable, and the failure it causes (a fragment rerun handing the next block
a stranger's children) is invisible in review. The branches now choose a STATE
and the single write happens after them, which makes the invariant true by
construction. Found by the FULL suite, after the targeted files were green.

## Coverage

- `tests/test_handoff.py` (30), driving the real listener over real HTTP.
- `scripts/_mutate_handoff.py` **19/19 caught**.
- **NOT VERIFIED END TO END.** The listener, the origin checks and the manifest
  are measured; what is unverified is the round trip through real Chrome to a
  real Canvas tab - install the extension, press the card, click the toolbar
  button, land signed in. The extension now LOADS (confirmed by the product
  owner's own attempt, which is what found the icon), so that is the next
  thing to try.

## Dev testing: `streamlit run app.py` CANNOT open the sign-in window (2026-09-12)
Reported by the product owner: *"when i run streamlit run app.py in the terminal,
i cant open the secondary browser for sign in with canvas authentication."* It is
not a bug and it never worked. **`webview.create_window` only really builds a
window when `webview.guilib` is already set, and the only thing that sets it is
`webview.start()`, which raises `WebViewException('pywebview must be run on a
main thread.')` anywhere else** (read out of the installed `webview/__init__.py`:
`guilib = initialize(gui)` at line 245 inside `start`, and the
`threading.current_thread().name != 'MainThread' and guilib` gate at line 419).
Under `streamlit run`, Streamlit owns the main thread, so `is_available()`
answers False correctly and the button refuses with a message.
- **`python dev.py` is the fix**: production's threading model with the app
  window swapped for a small status window. `webview.start()` on the main
  thread, the Streamlit server on a daemon thread in the SAME process, the app
  opened in the developer's own browser. Same process is load-bearing rather
  than tidy - the sign-in job, the loopback listener and the credential store
  are all process-global, so a dev loop running Streamlit separately would have
  the app talking to one set of globals and the web view to another.
- **It reimplements nothing, and `tests/test_dev_tooling.py` enforces that.**
  The product owner asked in as many words whether it mimics the auth screen.
  It contains exactly one page of its own, `_control_html`, and the test fails
  if that page ever gains an input, a form, a button, "sign in", "log in",
  "access token" or "canvas url" - i.e. if anyone starts rebuilding the login
  page inside the harness. It also asserts the app is launched through
  `start._launch_streamlit` rather than a second Streamlit CLI invocation, so
  the theme flags, the headless setting and the non-main-thread signal
  monkeypatch cannot drift.
- **`--window` exists because the DEFAULT is not production-faithful for
  LAYOUT.** By default the app is drawn by the developer's browser and the
  shipped app draws it in WebView2/WKWebView. Functionally that is nothing -
  there is **no `window.pywebview` or `js_api` call anywhere in the app**
  (verified by grep; `inject_app_shell_bridge` is pure DOM JS) - but layout is
  not a functional question, so `--window` loads the Streamlit URL into the
  pywebview window instead. `python start.py` was always production-faithful
  too; what it cannot give you is DevTools and a live DOM.
- **`debug` defaults to OFF even though this is a dev tool**, and that is a
  measurement decision, not caution. pywebview sets
  `AreDefaultContextMenusEnabled` ITSELF from its debug flag, and the sign-in
  window's right-click paste depends on that setting - so a dev host running
  with debug on would report pasting working whether or not the app's own code
  enables it. A harness that cannot reproduce the production failure is worse
  than no harness.
- **The banner's sign-in line is MEASURED, not printed.** It calls
  `is_available()`. The first version hard-coded "available", which is a claim
  wearing a measurement's clothes - and a False there means the GUI loop did
  not come up, so every sign-in test after it is void. A test pins it.
- **Run from source the config dir is the REPO ROOT** (`get_config_dir()`), so
  the profile is `<repo>/webview`, not `%APPDATA%/CanvasDownloader/webview`.
  `python start.py` has always behaved this way. Two consequences: signing in
  under `dev.py` does not sign you in inside the installed .exe, and the two
  cannot fight over the same WebView2 profile lock. `--isolated` adds a
  `webview-dev` sibling for testing a first-ever sign-in without signing
  yourself out of your own institution.
- **`is_available()`'s message is now branched on `sys.frozen`.** A packaged
  launch always runs `webview.start()`, so only a DEVELOPER can see this
  string; naming the launcher is right for a user and useless to a developer,
  who needs the command that works. Both wordings still offer the token, which
  `test_is_available_says_why_it_is_not` asserts.
- **MEASURED end to end, 2026-09-12**: `python dev.py --isolated --no-browser
  --port 8735` printed `Sign-in window   available`, and the real auth screen
  rendered at `?mode=auth` with title `Canvas Downloader` and **0 console
  errors**. An earlier attempt showed 25 `ERR_CONNECTION_REFUSED` errors, all
  of them AFTER a `timeout 75` killed the host - the frontend reconnecting to a
  server the harness had stopped, not a defect. **Check the timestamps on
  console errors before reading them as findings.**
- **The banner did not print under a redirect, and that was stdout buffering.**
  Python block-buffers a redirected stdout while Streamlit's own writes flush,
  so the banner appeared to be missing while the app was fine. Every print in
  both tools now passes `flush=True`. It only ever bit a redirect, never a
  terminal.

## The handoff listener had TWO framing bugs, and only a BROWSER could hit them (2026-09-12)
Found by building the dev-testing harness and reading what the listener put on
the wire - not by reading the code, and not by any of the 30 tests that already
covered it. The reason none of them could see it is the transferable part:
**`urllib` opens a connection per request, so an unread body is followed by EOF
and the server never trips over it. A browser keeps the connection and sends the
next request down it**, which is exactly the pair the extension makes -
`GET /ping` to find the port, then `POST /canvas-session`.
- **A refusal did not drain the request body.** Every refusal answers without
  reading it - a 403 for a page origin, a 404, a 409 when nothing is waiting -
  and with `protocol_version = 'HTTP/1.1'` the connection is keep-alive, so
  those bytes are still in the socket when the server goes looking for the next
  request line. MEASURED, one socket, two requests, with the drain removed as
  the control: the first answered `HTTP/1.1 403 Forbidden` and the second
  answered `HTTP/1.1 501 Unsupported method` naming the JSON body itself as the
  method, against `HTTP/1.1 200 OK` with the fix. The second request is the
  extension's own POST, so this is a handoff that cannot land on a connection
  the browser is entitled to reuse.
- **The CORS preflight returned a body with a 204.** RFC 9110: a 204 is
  terminated by the end of the header section, so it cannot carry
  `Content-Length`, and a client that knows the rule does not read the two bytes
  of the empty JSON object - they sat in the socket. MEASURED with the body
  restored: `Content-Length: 2`, client read **0** bytes, server raised
  `ConnectionResetError`; header absent and no traceback with the fix.
  **Chrome sends this preflight before EVERY handoff POST**, because
  `Content-Type: application/json` is not CORS-safelisted.
- **`_dispose_of_body` is called from `_reply`, not from each verb**, so it is
  true for the verbs not yet written. `_body_consumed` is claimed next to the
  real read, because draining a body that is already gone BLOCKS until the read
  timeout rather than returning empty. A body over `MAX_BODY_BYTES` is never
  drained - the connection is closed instead, since draining is a courtesy to a
  well-behaved client and not an obligation to read whatever a refused caller
  sent.
- **`handle_error` is overridden.** `socketserver`'s default prints a traceback
  to stderr, which is wrong twice here: `log_message` is silenced precisely so
  this listener never writes there, and a windowed Windows build has no stderr
  at all. A dropped connection logs at debug, anything else at warning with
  `exc_info` - reported, not swallowed.
- **A handler `timeout = 10` closes idle keep-alive connections**, so nothing
  can pile a thread up per connection by connecting and saying nothing.
- **MY OWN DETECTOR WAS LOOSE FIRST, and the control is what caught it.** The
  probe flagged "TRACEBACK" on any stderr output, so `logger.warning`'s own
  line (stderr via the last-resort handler) read as a traceback and the refused
  POST looked like a second crash. With the detector tightened to look for the
  word `Traceback`, the positive control did NOT fire - which is what proved the
  403 had never raised and sent me to the keep-alive probe that found the real
  mechanism. **A negative result from a diagnostic you have not controlled is
  worth nothing**, and here the loose one invented a bug and hid the real one.
- `scripts/check_handoff.py` settles three of the four possible causes of "the
  extension does not work" from the command line (the app is not running, the
  listener is not armed, the listener refuses what it is sent), so whatever is
  left is Chrome. It reads `core.handoff`'s own `PORTS` and `ACCEPTED_COOKIES` -
  a test forbids it hard-coding a port - and is NON-DESTRUCTIVE by default:
  every check either reads or is refused on purpose, and a refused POST never
  sets the payload, so the arming survives for the real extension. `--accept`
  consumes it and says so.
- `tests/test_handoff.py` section 6 (6 new tests); `scripts/_mutate_handoff.py`
  **24/24 caught**, including all five new mutants.

## `add_file_to_manifest` was flagged and does NOT reproduce (2026-09-12)
Carried from 2026-09-11 as "the same shape as the `record_downloaded_file`
defect, reachability not established". Reachability is what settles it, and it
had not been looked at.
- It hashes the file on disk whenever no md5 is passed, and writes that as
  `original_md5` - which is the sole basis of edit protection. That IS the
  shape of the 2026-08-20 data-loss defect.
- **But both call sites write the bytes immediately before calling.**
  `sync/execution.py:1128` (the real file download) passes
  `local_md5=_dl_hasher.hexdigest()`, so the disk hash never runs;
  `sync/execution.py:1735` (the synthetic shortcut / Canvas Page path) passes
  nothing, and every route to it writes the file first - the real page HTML,
  else the redirect stub, else the `.url` - while a path with nothing to write
  hits `continue` and never reaches the call. So the hash is always of bytes the
  app itself just wrote, which is the correct baseline. Same distinction that
  made the sibling's fix right: hashing is correct when the file is OURS.
- **The residual risk is that the invariant is stated in the docstring and
  enforced nowhere**, which is exactly how the sibling acquired its bug - a
  third caller was added later that recorded skipped-but-existing files, and the
  docstring stayed true of the original two.
  `test_the_SIBLING_writer_has_no_unclassified_caller` is the census: a new
  md5-less call site must either pass the bytes' own hash or be listed in
  `WRITES_ITS_OWN_BYTES` with the reason.

## The auth screen's LAYOUT, measured rather than described (2026-09-12)
The product owner: *"the UI of the auth screen - specifically with all the new
buttons - looks absolutely horrendous... you just nuked the layout."* Correct,
and the diagnosis is specific rather than aesthetic. Captured from the real
screen in `dev.py` before any redesign:
- **The two sign-in routes are OUTLINE buttons and the token route's `Log In` is
  SOLID PRIMARY.** So the route the product wants a student to take reads as the
  secondary option, and the dead end for a token-disabled institution is the
  most prominent control on the card. The visual weight is exactly inverted.
- **`Get a token` is ALSO solid blue**, so the lower half holds two competing
  solid buttons while the upper half holds none.
- **Two full-width outline buttons stacked** read as a pair of equals; nothing
  says which is the straight path and which is supplementary.
- **Three lines of small grey hint text are interleaved between the buttons**,
  so the stack reads as prose with controls embedded in it rather than as a
  choice.
- **The card is about 930px wide** for a form this simple, which stretches every
  full-width button into a slab.
- Not fixed in this pass: the product owner is supplying a reference, and
  guessing at it twice costs more than waiting once.

## VERIFIED ON REAL CBS CANVAS, by the product owner (2026-09-12, 22:57 to 23:19)
Five of the six items this file listed as "NOT VERIFIED END TO END" are now
measured, from the app's own log rather than from reasoning. The whole point of
that list was that none of it could be faked, so this is what closes it.

```
22:59:12  core.handoff       Accepted a Canvas session handoff for
                             cbscanvas.instructure.com (2 cookies).
22:59:21  core.token_mint    This Canvas account may not create its own access
                             tokens (HTTP 403); keeping the browser session.
23:13:36  core.browser_login Sign-in window: password manager on, context menu on.
23:13:39  core.browser_login Canvas sign-in window shown after 3.9s (the page
                             stopped moving - a human is needed).
23:19:30  core.browser_login Kept 31 session cookie(s) for 30 days so the next
                             launch can sign in without asking.
```

- **The extension handoff works end to end.** A real Chrome, a real Canvas tab,
  a real account: two cookies accepted and the app signed in. The route exists.
- **The mint against CBS answers HTTP 403**, which is exactly the prediction,
  and `token_mint` classifies it as `blocked_by_institution` - PERMANENT, so
  nothing retries - and keeps the browser session. The expected-refusal path is
  the one CBS's population actually takes, and it is now the measured one.
- **The password manager and the context menu are both ON in the real window.**
  That line is a read-back, not a write, so it is evidence rather than intent.
- **The sign-in window appears in 3.9s** when the silent attempt cannot finish,
  which is the constant this file argues about at length. Measured once, on a
  real SSO chain.
- **THE RETENTION MECHANISM IS REAL: 31 session cookies re-dated to 30 days.**
  That is the whole feature working on a live Entra tenant plus Canvas, not on
  a synthetic profile. Whether the next launch signs in silently still needs a
  day to pass; what is proven is that the cookies survive with dates on them.
- **Entra's "Stay signed in?" prompt RENDERS IN WEBVIEW2.** Screenshotted:
  *"Vil du forblive logget på?"* with Ja/Nej, plus the MFA *"Spørg mig ikke
  igen før om 30 dage"* tick. This was the single most load-bearing unknown in
  the feature - the app's copy tells the student to use that tick box, and
  until now nothing proved the box could even appear inside the app's window.
  It can, and the product owner ticked both.

### The app's sign-in window CANNOT use Chrome's saved passwords, ever
Reported: *"on windows its only the windows hello passwords that come up in the
login window... if it could run on chrome we should prefer that."* It cannot,
and the reason is structural rather than a setting anyone can flip.
- **The window is WebView2**, which is Edge's engine, running against **our own
  `storage_path` profile**. A WebView2 host chooses a user-data folder; it
  cannot be pointed at the user's real Chrome profile (different browser
  entirely) and must not be pointed at their real Edge profile (unsupported,
  and it conflicts with Edge actually running). Chrome's App-Bound Encryption
  closes the file route from the outside, deliberately.
- **What DOES appear is Windows Hello passkeys**, because those are an
  OS-level platform authenticator available to any browser through WebAuthn.
  That is why the list read *"Adgangsnøgle - Windows Hello"* rather than saved
  passwords.
- **So there are exactly two honest answers, and both are already built**: the
  browser EXTENSION, which runs inside the Chrome where those passwords live
  and is precisely the supported way to reach them; and the app's own password
  manager, which remembers the password after the student types it once in the
  app's window and autofills it afterwards.
- Do not re-open this as "point WebView2 at the user's profile". It is not a
  supported configuration and the failure mode is a corrupted browser profile.

### Small thing seen in the same log, not yet chased
`23:08:03 ui.auth Keyring delete_password failed: CanvasDownloader` on logout.
Probably benign (deleting an entry that is not there), but it is logged as a
failure and a logout that cannot clear the store is worth being sure about.
Reachability not established; nobody has reproduced it deliberately.

## The extension: what using it for real exposed (2026-09-12)
The product owner installed it, signed in with it, and reported every rough
edge. All of it was fixed in the same pass.

### The first click did nothing, and it was not a race
*"first time i clicked on the button in the extension... google chrome asked for
a permission, after which nothing happened in neither the extension or canvas
downloader. Then i waited 5 minutes and tried again - that time... it logged
in."*
- **`chrome.permissions.request()` destroys the popup that called it.** The
  prompt is Chrome-owned, the popup loses focus, and a popup that loses focus is
  torn down - so the promise being awaited never resolves and every line after
  it is dead code. The second attempt works because the permission is already
  held, `request()` resolves instantly, no prompt appears and the popup lives.
- **The fix is that the work moved to a service worker.** A worker is not torn
  down by a focus change, and `chrome.permissions.onAdded` fires there - which
  is exactly the signal the first attempt was missing. The popup now stores the
  pending target, asks, and dies; the worker finishes the sign-in and puts a
  tick on the icon. `extension/background.js`.
- The popup also reads `chrome.storage.session.lastResult` on open, so a student
  who reopens it after granting is told "Done" rather than being walked back
  through a flow that already completed.

### The address was invisible, and the cascade was why
*"the url in the chrome extension is almost invisible."* The dark-mode block sat
ABOVE the base rules, so the later `.host { background: #f0f2f6 }` won on equal
specificity while `body` kept its dark-mode light text. Light text on a light
box. **Every colour is now a token on `:root` and the dark block redefines only
tokens**, which makes the whole class impossible: there is one place a colour is
chosen and a component rule cannot out-order the media query.

### Developer wording is BANNED, and it is a test
*"'Send my session' is scary and developer wording - developer wording IS BANNED
FROM THE CHROME EXTENSION COPY."* `test_no_DEVELOPER_WORDING_reaches_the_student`
fails the build on 19 words (session, cookie, token, origin, host, port,
handoff, payload, endpoint, json, http, api, csrf, credential, auth, header...)
in anything a student can read: the popup's HTML text, its quoted strings, and
the manifest's name/description/title.
- **Writing that guard cost three false findings, and each is a trap this repo
  already records.** A `"..."` regex paired the wrong quotes around
  `'<span class="spin"></span>'`; stripping `/* */` first ATE the `/*` inside the
  template literal `` `${url.origin}/*` `` and swallowed forty lines of code as
  "copy"; and `\b` written through a shell heredoc became a literal BACKSPACE
  byte (0x08), so the pattern matched nothing and the guard passed on
  "Send my Canvas session". **Only the positive control found any of it.**
- Strings and comments are now read by ONE left-to-right scanner, because each
  construct can contain the other. Interpolated template literals are excluded
  as code; a backtick string with no `${` is still treated as prose.

### The popup is a guide now, not a button
Three steps that know which one the student is on, driven by real state: is this
tab Canvas, is the app open, is it waiting, is the permission held.
`extension/canvas-hosts.js` answers the first, **generated from
`shared/institutions.py`** by `scripts/build_extension_hosts.py` so there is no
second hand-written list - of 4,757 known schools a `.instructure.com` suffix
plus the word "canvas" recognise all but 100, and only those 100 ship.

### The icon says when to click, without watching anything
A once-a-minute `chrome.alarms` tick asks the app on this machine whether it is
waiting, and shows a blue dot if so. **There is no `tabs` permission**, no
content script and no host permission at install, so the extension is never told
which sites the student visits - which was the product owner's own stated worry
about a readiness indicator backfiring. A test forbids `tabs`, `webNavigation`,
`history`, `browsingData` and content scripts from ever being added.

## Using the extension for real, round two (2026-09-13)
The product owner installed the rebuilt extension and reported four things. All
four were real.

### The popup could HANG, and a popup that hangs says nothing
Reported stuck on *"Checking / One moment"*. Two unbounded waits could produce
it and both are now closed:
- **`findApp()`'s `fetch` had no timeout.** A closed port refuses instantly, so
  this only bites when something ACCEPTS the connection and then says nothing -
  another program on 53127-53129, or a stalled app. `AbortSignal.timeout(1200)`
  per port, and 8s on the POST.
- **`chrome.runtime.sendMessage` never answers if the worker failed to start**,
  and the callback simply never fires - `lastError` is not always set. The popup
  now races every request against `ASK_TIMEOUT_MS` and renders the "not
  running" state rather than waiting.
**A popup is the only surface this feature has.** Anything it waits on has to
have a deadline, because there is no second place for the student to look.

### The spinner did not move, and the cause is probably a system setting
`@media (prefers-reduced-motion: reduce)` had `.spin { animation: none }`,
which leaves a STATIC RING - and a ring that does not turn reads as broken
rather than as "animations are off". Windows 11's *Animation effects: off* sets
that media query. It is now `display: none` there, so the state shows its text
and nothing pretends to spin. **Not confirmed against that setting on the
reporting machine**; the CSS is wrong either way.

### The extension must say whether the app is ON or OFF, always
*"we should let the user know visually and with text whether or not canvas
downloader is ON or OFF."* There is now a permanent row under the brand, and
`read()` fills it FIRST - before the tab checks - because the screen that
prompted this was the wrong-page one, which said nothing about the app at all.
Three states, not two: **not running**, **running but not asking for a sign-in
yet**, and **running, ready to log in** with a tick. Collapsing the middle one
into "not running" would send a student looking for the wrong problem.

### Copy, dictated
Step 3 is *"Come back here and click **Sign me in**"*, and the footer is *"This
extension never looks at any pages you visit."* Both verbatim.

### `node --check` is now a test
A JavaScript syntax error makes the extension inert and Chrome reports it
nowhere a student would look - the same shape as the missing icon. Every
`extension/*.js` is parsed by node in `test_every_extension_script_PARSES`,
skipped rather than passed vacuously where node is absent.

## Opening the student's Canvas for them (2026-09-13)
*"we literally create friction by having the user manually find their URL when
their URL is already typed in."* `ui.auth.open_canvas_tab` opens it, and
`begin_browser_handoff(api_url)` calls it **after** `handoff.start()` - the
extension asks whether the app is waiting the moment it is clicked, so opening
the tab first leaves a window in which the honest answer is "not waiting".
- **`normalize_canvas_url` is NOT a validation gate and treating it as one was a
  defect a test caught.** It is deliberately forgiving because it feeds a field
  the user is about to submit, which the app then validates against Canvas.
  Measured: `not a url` -> `https://not a url`; `file:///C:/Windows` ->
  `https://file:`; `javascript:alert(1)` ->
  `https://javascript:alert(1).instructure.com`. None can execute anything -
  they are all `https` - but every one would open a junk tab and the app would
  be blamed for it.
- So `open_canvas_tab` asks two more questions before handing anything to the
  OS URL handler: the scheme must be one we chose, and the host (via
  `canvas_host`, the app's own rule, not a second copy) must contain a dot and
  no whitespace. Five hostile inputs are parametrised in the tests.
- **The waiting notice has two sentences and one shape.** Having opened their
  Canvas for them, telling them to go and open it is wrong; `handoff_opened_tab`
  decides which sentence, and `cancel_browser_handoff` pops it so the NEXT
  attempt cannot inherit a claim that is no longer true.

## A normal logout logged a failure (2026-09-13)
`Keyring delete_password failed: CanvasDownloader`, seen twice in one evening.
`keyring.errors.PasswordDeleteError` is what the Windows backend raises when
there is **nothing to delete**, and its message is only the service name, which
is why the line read as though the service were the error. There is often
nothing to delete BY DESIGN: a browser-login credential is about 3,260 bytes
and Credential Manager refuses anything over 2,560, so it lives in the DPAPI
fallback and no keyring entry was ever written. Absent is now success at debug;
a real failure is still a warning, **and both directions are tested** - logout
is the one action whose job is to leave nothing behind, so "it was already
empty" and "it would not clear" must never look the same.

## Extension round three, and a credential the app could not recognise (2026-09-13)
Reported after real use. See `tests/audit/OWNER_REPORTS.md` for the two defects
in full (the reloaded-module `TypeError`, fixed; the handoff port leak, open).

- **The popup could HANG on "Checking"**, so both ends are bounded now:
  `AbortSignal.timeout` on every request the worker makes to the app, and a
  deadline on the popup`s own `sendMessage`. A popup is the only surface this
  feature has - anything it waits on needs a deadline.
- **No step is highlighted while the app is OFF** (`current === 0`). Lighting
  step 1 told the student to do something that could not help them yet.
- **The success state marks all three done** (`current > 3`); step 3 used to
  stay blue after the sign-in finished, so the guide never completed.
- **The state dot carries no glyph.** A tick inside a 9px circle landed on top
  of the dot rather than beside it.
- **A "Check again" control** sits at the far right of the state row, because
  the app can start after the popup opened.
- **Reduced motion hides the spinner rather than freezing it.** A ring that
  does not turn reads as broken; Windows 11`s "Animation effects: off" sets
  that media query, which the product owner has on.
- Copy, dictated verbatim: step 3 is *"In your Canvas page, open this
  extension and click Sign me in"*, footer *"This extension never looks at any
  pages you visit."*

**NOT DONE, and it needs a design decision**: a clean "Canvas Downloader is
logged in and running" state with no steps. The extension can only learn that
from `/ping`, and the listener is deliberately NOT a standing fixture - it runs
only while a sign-in is being asked for. Reporting signed-in state would mean
either keeping a socket open for the life of the app (against the threat model
in this file) or a second always-on endpoint (the same thing wearing a hat).
Do not build it without settling that first.

## 2026-09-13: the extension CANNOT ask whether the app is signed in, so it remembers

The product owner, having used it: *"if we cant properly tell if the app is
actually running after the sign-in, then the extension should be designed
around that."* He is right about the premise, and the premise is measurable.

**The mechanism.** `do_POST` sets `_state['open'] = False` on the accepted
handoff, and `ui/auth.py` consumes it and calls `handoff.stop()`, which closes
the socket. So there are three states within about two seconds of a SUCCESSFUL
sign-in:

| moment | `/ping` answers | what the popup showed |
|---|---|---|
| waiting | `{waiting: true}` | "Running, ready to log in" |
| accepted, not yet consumed | `{waiting: false}` | "Running, but not asking for a sign-in yet" |
| consumed and stopped | nothing at all | **"Canvas Downloader is not running"** |

The third line is the honest reading of silence and it is what a student meets
**immediately after the thing worked**. Pinned by
`test_the_LISTENER_REALLY_DOES_STOP_after_a_handoff`, which drives all three
transitions against the real server - so if the lifecycle ever changes, the
screen built on top of it fails in the same commit.

**The wrong fix is to keep the socket open.** A standing listener is exactly
what section 3 of `tests/test_handoff.py` exists to prevent, and the one-shot
time-boxed window is the reason opening a port on a student's machine is
defensible at all. A second always-on endpoint is the same hole with a
different name.

**The right one is that the extension never needed to ask.** IT PERFORMED THE
SIGN-IN. `background.js` writes `signedIn` into `chrome.storage.session` on a
successful result - a lifetime that dies with the browsing and never touches
the disk - and the popup reads that instead of interrogating an app that has
deliberately stopped answering.

- **A LIVE REQUEST ALWAYS BEATS THE MEMORY.** `read()` consults `signedIn` only
  when `app.waiting` is false. Without that ordering a remembered sign-in hides
  a real one - the app reopened, the session expired, they logged out - and the
  student has no route back to the guide. It is the one invariant here that can
  strand somebody, so it is anchored on the literal guard expression and the
  test strips comments first: the guard sits directly beneath a comment
  explaining the rule, and an unstripped search passes on the prose. That trap
  has cost this repo four findings.
- **The way back forgets.** "Something not right? Go through the steps again"
  removes `signedIn` rather than merely re-rendering. A student clicking it is
  saying the memory does not match what they see, so it has earned no more
  trust; the next successful sign-in writes it again.
- **The countdown is a NUMBER, not a bar.** Five seconds from the finished
  screen to the resting one, asked for directly. The machine that reported this
  feature's first spinner as "doesn't move" has Windows animation effects off,
  so `prefers-reduced-motion` is set there - a draining bar would be invisible
  on exactly the machine that needs the signal. A counting number is content.
  A mutant that adds `.countdown` to the reduced-motion block is caught.
- **The popup no longer closes itself.** It used to shut 2.2 s after a
  sign-in. Since the app cannot send a confirmation, that screen is the ONLY
  confirmation a student ever gets, and it was being thrown away.
- **`body.resting` is checked as a CENSUS, not a spot check.** The resting
  screen is the shape this repo's most expensive defect class takes - one more
  element added to the guide leaks onto the clean screen unless somebody
  remembers. `test_EVERY_part_of_the_guide_is_hidden_on_the_resting_screen`
  enumerates the body's top-level blocks and fails on any the rule does not
  name, so the next element cannot be forgotten silently.
- **Two success paths, one implementation.** Clicking the button, and reopening
  after Chrome's approval prompt destroyed the popup mid-sign-in, both call
  `showDone()`. They used to render the finished screen separately, and the old
  test counted the copies - which is how a test comes to enforce duplication.
  It now counts the CALLS.

**Driven, not reasoned.** `popup.html` and `popup.js` were served over HTTP and
run in real Chromium with only the `chrome.*` APIs stubbed, in both colour
schemes: the guide at step 3, the click, the countdown ticking 5 -> 3, the
landing, a reopen with the app off, the way back, and a live request arriving
while a sign-in was remembered. Every probe carries a positive control - a
forced overlap and text painted its own background colour both fire - because
a clean run from a detector that has never said yes is worth nothing. Two real
defects came out of it that reading had not: the finished screen's heaviest
element was a disabled button nobody could press, and the harness's own
scenario was being reset by `page.goto` re-running the init script, which had
it reporting a product failure that was the harness forgetting.

## 2026-09-13: A MODULE RE-IMPORT ORPHANS THE LISTENER, and the orphan answers

This is the same root cause as the `CanvasCredential` TypeError above, in a
different place, and it is worse because everything downstream reports success.

**Mechanism.** `streamlit/watcher/local_sources_watcher.py` does
`del sys.modules[name]` for **EVERY watched module on ANY file change** - its
own comment: *"as a workaround we simply unload all watched modules"*. So
`core.handoff` is re-imported FRESH. The new module's `_server` is None, while
the socket the previous incarnation opened is still LISTENING in a
`serve_forever` thread that nothing holds a reference to. Nothing can call
`stop()` on it, ever.

**Measured**, on three throwaway ports, before the fix:

```
start()                      -> 53500   listening: [53500]
re-import; start()           -> 53501   listening: [53500, 53501]
re-import; start()           -> 53502   listening: [53500, 53501, 53502]
re-import; start()           -> 0       "Could not open a handoff port"
```

Confirmed in the field the same night: `netstat -ano` showed ONE
`python dev.py` (PID 12848) holding **53127, 53128 and 53129 all LISTENING**,
matching its own log walking 53128 -> 53129 -> 53127.

**THE SECOND CONSEQUENCE IS THE ONE THAT COSTS A SIGN-IN.** The extension walks
the port list and takes the FIRST port that answers, which is the OLDEST
ORPHAN. That orphan answers `/ping`, reports itself armed, accepts the handoff
and logs *"Accepted a Canvas session handoff"* - into a `_state` the live
module cannot read. So:

- the extension showed its success screen (it got HTTP 200, correctly);
- the terminal printed `Accepted a Canvas session handoff for ...`;
- `scripts/check_handoff.py` passed **ten of ten** checks;
- and the app said **"Canvas sign-in did not finish"**, because `result()` on
  the live module returns None for ever.

Three independent "it worked" signals and a failure. That is what makes this
worth a long entry.

**The fix: hold the socket where a re-import cannot reach it.** `_RUNTIME_KEY =
'canvas_downloader._handoff_runtime'` is a synthetic `types.ModuleType` in
`sys.modules`. It has **no `__file__`**, so the watcher never watches it and
never deletes it. The server, the lock and the state dict live on it.
`_lock` and `_state` are then bound to the runtime's own objects at import, so:

- a re-imported module ADOPTS the running listener (`start()` takes its
  idempotent branch) instead of binding the next port;
- an orphaned HANDLER from a previous incarnation still writes into the SAME
  state dict, because its globals were bound to these same objects. That is the
  half that makes the sign-in arrive.

**Why the obvious fixes are wrong.** `SO_REUSEADDR` is not it - the ports are
genuinely LISTENING, not in TIME_WAIT (an earlier version of this entry
hypothesised TIME_WAIT and was WRONG; the suite bound straight through the
TIME_WAIT rows that were present). Nor is it `stop()` being buggy: `stop()` is
correct and simply never gets called, because the only reference is gone.

**SOURCE RUNS ONLY.** `start.py` passes `--server.fileWatcherType=none` when
frozen, so the shipped app has no watcher. `python dev.py` and `python start.py`
do.

**`scripts/check_handoff.py` now probes EVERY port, not just the first**, and
FAILS when more than one answers, naming the state. A checker that stops at the
first answer cannot tell a healthy app from an orphan the extension will reach
first, which made it worse than no checker. It has a positive control
(`test_the_checker_still_PASSES_that_check_with_one_listener`).

Covered by section 9 of `tests/test_handoff.py`, which drives the REAL
`del sys.modules` path rather than `importlib.reload` - those are different
(reload re-executes into the existing dict) and only the former is what
Streamlit does.

## 2026-09-13: THE MUTATION PASS PRINTED 38/38 WHILE THREE MUTANTS SURVIVED

The most important entry of the day, because it is about a number that gets
written down.

The pass ran while a `python dev.py` held all three handoff ports. The
`listening` fixture could not bind, so **26 tests ERRORED on every single run**
- baseline included? No: the baseline ran before the dev host armed them, and
went green. From the moment the ports were taken, every mutant was reported
CAUGHT by a broken fixture rather than by a test. **38/38.**

Re-measured with the ports free: **three of those mutants survive.**

- the scheme gate in `open_canvas_tab` - genuinely untested, because
  `normalize_canvas_url` prepends `https://` to everything, so the parametrised
  test's hostile values all arrive schemed and the HOST check does the
  refusing. Now driven directly, with the normaliser patched.
- the keyring absent-entry rule - its tests live in
  `tests/test_keychain_unlock.py`, which was not in the harness's `TESTS`.
- the same one in its `_NeverRaisedHere` form, which was a strawman anyway: it
  introduces a `NameError`, so anything touching the path catches it for the
  wrong reason. Replaced by the plausible edit (report absent as a failure).

**Three guards added, because this must not be able to happen again:**

1. `_ports_held()` runs as a PREFLIGHT and refuses to start when anything is
   listening on the handoff ports, printing why.
2. `_run_tests()` returns the pytest COUNTS, and a mutant run that produces
   more skips or errors than the baseline ABORTS the pass. A mutant must be
   caught by a FAILURE; anything else means the run did not exercise it.
3. `TESTS` gained `tests/test_keychain_unlock.py` and
   `tests/test_dev_tooling.py`.

**The rule, which generalises past this harness**: a mutation score is only
evidence if the suite that produced it was actually running. "Caught" and
"the fixture exploded" are indistinguishable from the outside, and the failure
direction is the dangerous one - it manufactures confidence. Whenever a pass
comes back 100%, spot-check one mutant by hand and read WHICH tests failed.

**Operationally**: do not run this harness while `dev.py` is up, in either
direction. The harness writes to `core/handoff.py`, `ui/auth.py` and `app.py`
dozens of times, and each write triggers the watcher that orphans the dev
host's listener - which is exactly how the field reproduction above was
created.

## 2026-09-13: WHY FOUR SESSIONS EACH DECLARED THIS FEATURE WORKING WHILE IT WAS BROKEN

Asked directly by the product owner, and it is the most valuable question in
this file, so the answer is mechanism-first like everything else here. None of
what follows is about the bug. It is about how three independent "it worked"
signals were produced by something that had never worked.

### 1. This file did not LOAD in the files that implement the feature

`.claude/rules/*.md` load by `paths:` frontmatter. This file's list was:

    core/canvas_auth.py, core/browser_login.py, ui/auth.py, start.py

The feature is also `core/handoff.py`, `extension/`, `dev.py` and
`scripts/check_handoff.py`. **None of them was on that list**, so 2,200 lines
of rules written for exactly this feature were unreachable from most of it.
`scripts/check_*.py` is claimed by `release-and-packaging.md`, so the sign-in
verification tool loaded PACKAGING rules: not the absence of context, the wrong
context.

**The general shape: routing by filename delivers nothing to a NEW file, and a
new file is where the accumulated lessons are most needed.** Nobody notices,
because a rule that did not load is indistinguishable from a rule that does not
exist. Fixed: the `paths:` list above now names every file of the feature, and
`tests/test_rule_routing.py` fails on any app module no rule file claims.

### 2. The class was found, fixed, TESTED, and not swept - forty minutes before it bit

- `core/handoff.py` was written 2026-09-12 holding `_server`, `_state` and
  `_lock` as module globals.
- At about 00:27 on 2026-09-13 the module-reload hazard was diagnosed in
  `core/canvas_auth.py`, fixed, and covered by
  `test_a_credential_from_a_RELOADED_module_is_adopted`, which drives a REAL
  `importlib` reload.
- At 01:09 the product owner hit the identical hazard in `core/handoff.py`.
  Same feature, one file over, and worse: a module global that owns an **OS
  resource** rather than a value.

CLAUDE.md's first standing rule is that a fix is not done until every site of
its class has it. The class was in hand, with a test written for it, and the
question *"what else in this feature holds process-global state across a
re-import?"* was never asked. **Finding a hazard class and writing its test is
the moment to sweep, not the moment to move on.**

### 3. The checker shared the product's premise, so it could not falsify it

`background.js` finds the app by taking the FIRST port that answers.
`check_handoff.py::_discover` found the app by taking the first port that
answers. A verification tool that reimplements the assumption under test cannot
test it: it reported **ten of ten passing** while talking to an orphan.

**A checker must not discover its target the way the product does.** Where it
has to, it enumerates every candidate and fails on multiplicity, which is what
that file does now.

### 4. Success was asserted at the sender's boundary, never the receiver's

Each layer checked its own edge and called it done:

| what said "success" | what it actually proved |
|---|---|
| the extension's green screen | an HTTP 200 came back from *something* |
| `Accepted a Canvas session handoff` | *a* listener parsed the body |
| `check_handoff.py` 10/10 | *a* listener behaves correctly |

All three were true. All three were about an orphan. **Nothing anywhere
asserted the only fact that matters: the app now holds a credential it did not
have before.** For anything crossing a process boundary, a 2xx is the sender's
opinion; the RECEIVER's observable state is the oracle.

### 5. The test environment structurally could not contain the defect

`pytest` imports each module once and runs no file watcher. The defect requires
a watcher. So no quantity of tests in that environment could ever have found
it, and "the suite is green" was a claim about the test process only.

**Before calling a feature verified, name what production does that the
evidence did not cover** - module re-imports, a second window, a frozen bundle,
another process holding the same resource. Here the delta was one line long and
nobody wrote it.

### 6. The count of checks was irrelevant, because they were not INDEPENDENT

This is the sentence worth keeping. Tests, checker and harness were written by
the same author in the same sitting from the same mental model, and all three
inherited one assumption: *there is exactly one listener and it is ours.* The
defect lived precisely there. Evidence only adds up when the pieces can fail
separately, and these could not.

The mutation pass is the same failure in miniature: **38/38 produced by a
fixture that could not bind a port.** A number that cannot go down is not a
measurement.

### What was NOT the problem, stated so the next session does not over-correct

The threat model was done properly - loopback only, extension origins only, the
one-way CORS grant, the time box, the one-shot window - and every one of those
is driven against the real server and mutation-tested. Those tests are real and
they still pass. **What was missing was not rigour about security; it was any
model of the feature's own RUNTIME**: who owns this socket, what can destroy
the reference to it, and how many of them can exist at once. A carefully
secured feature with no lifetime model.

### The five questions that would have caught this before a line was written

Ask them of anything that spans a process, a thread or a window:

1. **What state outlives one function call, who owns it, and what can destroy
   the owner?** Here: a socket owned by a module global, destroyed by a file
   watcher nobody had thought about.
2. **How many instances of this can exist at once, and what happens to the
   second one?** Three, and it answered first.
3. **What is the receiver-side fact that proves success, and what reads it?**
   "The app holds a credential it did not have" - nothing read it.
4. **What does the real environment do that my tests do not?** Re-import every
   module on every edit.
5. **Does my checker find its target the same way the product does?** Yes, so
   it agreed with the product about the thing the product had wrong.

## 2026-09-13: THE SIGN-IN CARDS, and why "fix the three bugs" was the wrong answer

The product owner, after a run where the extension showed a green success
screen with a countdown and the app showed *"Canvas sign-in did not finish"*:
*"dont just fix these bugs. think a little deeper about it... We need to make
the cards in the app UI perfectly follow the different steps and not mess up
like they have."* He was right, and the three faults below only make sense read
together.

### THE TWO ROUTES ARE NOT ONE ROUTE, and the copy must never cross over

Stated by the product owner the same night, because it is the thing a shared
notice slot makes easy to get wrong:

* **Path A - "Sign in with Canvas"** opens the app's OWN Canvas window
  (pywebview). It needs **no extension**. States: `waiting`, `checking`,
  `cancelled`, `error`.
* **Path B - "Use the Canvas tab in my browser"** is the Chrome handoff and
  **REQUIRES the extension**. States: `handoff`, `handoff_arrived`, and five
  `fail:<cause>` cards.

They share one keyed slot (only one can be in flight), and that is fine. What
is not fine is Path A's failure telling somebody to install an extension - it
sends them to fix something unrelated to what went wrong - or Path B's failure
omitting it, since a missing extension is its single most likely cause.
`test_the_PATH_B_card_names_the_extension_and_PATH_A_never_does` pins both
directions.

### Fault 1: ARRIVAL SWITCHED OFF THE COLLECTOR

`waiting_handoff` was `handoff_waiting and handoff.waiting()`, and
`handoff.waiting()` means *"the window is still ACCEPTING"* - which stops the
instant a handoff lands. The polling fragment is rendered only while that is
true, **and that fragment is the only thing that asks for the full Streamlit
run which collects the credential**. So the arrival of the sign-in turned off
the thing that would have picked it up.

A one-second tick normally wins that race, which is why it works on a fast
machine. It loses when the app tab is backgrounded - and the app had just
opened a Canvas tab **in front of itself**, so it always is. On a slow laptop
Chrome throttles the timer and the credential sits uncollected until the
student presses the button again, at which point `app.py`'s
`adopt_pending_browser_login()` runs near the top of the run and signs them in.
**The log proves it: there is no second `Listening for a Canvas session
handoff` line**, because `start()` is idempotent - the listener had been armed
the whole time.

`core.handoff.has_payload()` is the non-consuming answer to the question
`waiting()` cannot be made to answer, and the two are opposites at exactly the
moment that matters.

### Fault 2: A STALE FAILURE OUTRANKED AN ATTEMPT IN FLIGHT

`begin_browser_handoff` cleared NEITHER failure flag (`handoff_failed` is only
popped in `cancel_browser_handoff`; `browser_login_failed` was popped nowhere
near this path). Both routes share the slot, so a previous attempt's error card
was drawn over a sign-in that was working. It clears both now, and the in-flight
branch is chosen before the failure branch - pinned by a test that compares
their positions in the source rather than trusting the reading.

### Fault 3: FIVE DIAGNOSES WERE COMPUTED AND THROWN AWAY

`render_browser_login_notice` used the failure only as a **truthiness test**:

```python
failed = (browser_login_failed or handoff_failed or '')
```

So five carefully-worded causes reached one generic card. The student holding a
perfectly good credential was told the sign-in did not finish, with no way to
tell that from a tab that was never signed in.

The fix keeps the safety property that made the loss happen. `_browser_notice_html`
is literals-only *by design* - a message that came back from a server must never
reach an unescaped render - so the causes became **KEYS** (`no_arrival`,
`canvas_refused`, `empty_tab`, `no_port`, `adopt_error`) looked up in
`_HANDOFF_FAILURES`, a table of literal pairs.
`test_every_failure_the_APP_can_set_HAS_a_card` walks the AST of the two
setters and fails on a cause with no card, so the next one cannot go missing.

### Fault 4 (latent, fixed): RE-ARMING DISCARDED AN UNCOLLECTED CREDENTIAL

`start()`'s idempotent branch did `_state.pop('payload', None)`. The only thing
that can be sitting there is a session the same student sent seconds ago, and
the student pressing the button again is **exactly** the one who could not see
that it had worked. `app.py` collects near the top of the run so the pop almost
never wins the race - which is why this was latent rather than the reported
bug - but destroying their credential at that moment is the worst available
answer. It is kept now.

### WHAT WAS DONE FOR THE STUDENT, not for correctness

- **The puzzle-piece sentence.** Chrome hides a newly-installed extension
  behind the puzzle-piece icon, so a student who has just added it is hunting
  for a button that is not on screen - and every other sentence in that card
  assumed they could see it. This is the highest-value line in the feature.
- **The dead end is closed.** Clicking Path B without the extension used to
  mean three minutes of waiting and then a generic failure. The card now says
  outright that the button not being there means the extension is not
  installed, and names Path A, which needs none.
- **"Listening" is gone.** It was developer wording under a spinner, on the one
  feature where telling a student that something is *listening* is the wrong
  thing to say about it. The extension's ban now covers the app cards, enforced
  by `test_NO_developer_wording_reaches_the_APP_cards_either`.
- **`handoff_arrived` exists.** Without it the two halves of one flow
  contradicted each other: green on one screen, failure on the other.

### The testing lesson, which is the transferable half

`test_the_notice_says_what_ACTUALLY_happened` was anchored on one SENTENCE and
failed the moment the copy improved while the behaviour it is named after was
perfectly intact - the brittle-anchor trap this repo already documents twice.
It now **renders both branches** through a stubbed `st.session_state` and
compares them, which is what its own name always claimed it did. Copy is going
to change; behaviour is what a test should hold.

All eight fixes were mutation-checked BY HAND before being written into
`scripts/_mutate_handoff.py` (now 54 mutants), so what is recorded there is a
measurement rather than an intention.

## macOS PARITY, as of the first sprint (2026-09-13) - asked for directly

The product owner's requirement is that macOS works exactly like Windows. Here
is where the three sign-in routes actually stand. **Nothing below has been run
on a Mac**; it is read out of pywebview 6.1's own source and this codebase's
platform guards.

### Route C, the browser extension: AT PARITY, and structurally so
`core/handoff.py` contains **no platform branch at all** - stdlib
`http.server` on loopback, `json`, `threading`. The extension is Chrome, which
is the same product on macOS. `open_canvas_tab` goes through `webbrowser.open`.
`scripts/check_handoff.py` and `dev.py` are equally platform-free.
So the route the owner verified end to end on 2026-09-13 is the one with
nothing left to port. **If macOS parity has to be bought cheaply, this is the
route to lead with.**

### Route A, the access token: at parity, untouched by this work

### Route B, the in-app sign-in window: BEHIND, in three named places
All three are `if sys.platform != 'win32': return`, so they are silent no-ops
rather than failures - macOS simply gets less:

| function | what Windows gets | what macOS gets |
|---|---|---|
| `enable_password_manager` | WebView2's `IsPasswordAutosaveEnabled` on, so the institution password can be saved and filled | **nothing** - WKWebView has no equivalent for a non-browser app, so a Mac student types a full institutional password on EVERY sign-in |
| `persist_session_cookies` | the app's own "stay signed in", re-dating session cookies in place | **nothing** - at an institution whose IdP offers no "stay signed in", a Mac user re-authenticates every launch |
| `_clear_profile_identity_data` | `ClearBrowsingDataAsync` reaching saved passwords and autofill on logout | **returns False** - `clear_cookies()` still runs and is in fact BROADER (all website data types), but the saved-password half is unreached |

### Four structural differences already read out of pywebview
- **`storage_path` is IGNORED on macOS.** `cocoa.py` always uses
  `WKWebsiteDataStore.defaultDataStore()`. The `webview/` folder is EMPTY
  there; the profile is in `~/Library/WebKit/<bundle id>`. `dev.py`'s "Web view
  profile" line is a Windows truth.
- **`get_cookies()` scopes differently**: macOS filters by SUBSTRING of the URL
  the window was OPENED with; Windows scopes to the CURRENT url. Same answer
  for Canvas, but a sibling host that is a substring of the login URL would be
  included on macOS only.
- **`clear_cookies()` is fire-and-forget on macOS** (`AppHelper.callAfter`,
  completion handler ignored) against a synchronous `Invoke` on Windows. So
  "log out and quit immediately" is verified on Windows and **cannot** be
  verified from here.
- **Google SSO is the open risk.** Google's embedded-webview policy names
  `WKWebView` explicitly and does NOT name WebView2 - which is why Windows was
  measured working with no change. A Google-SSO institution may therefore be
  BLOCKED on macOS while working on Windows. **Measure it; do not assume it
  fails, and do NOT "fix" it by spoofing the user agent** (`user_agent` is a
  `webview.start()` parameter, i.e. process-global, and it would be deliberate
  circumvention of a provider's security control - detect and report instead).

### The order to work in, when a Mac is available
1. Drive route C end to end - expected to pass, and it is the cheap win.
2. Drive route B against a SAML/CAS institution, then a Google one.
3. Decide whether B's three missing pieces are worth WKWebView equivalents, or
   whether macOS should lead with C and the token. That is a product call, not
   an engineering one, and it should be made with the measurements in hand.
