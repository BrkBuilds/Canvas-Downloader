# Canvas Downloader Connector

Signs you in to Canvas Downloader from the Canvas tab you already have open.
Nothing to type, nothing to copy.

It is **optional**. Canvas Downloader signs in perfectly well on its own; this
removes the last bit of typing for people who would rather not do it.

## Installing it

The store listings are not set up yet, so it is a Developer-mode install:

1. Open `chrome://extensions` (or `edge://extensions`).
2. Turn on **Developer mode**.
3. **Load unpacked**, and pick this `extension/` folder.

## Using it

1. Open your Canvas page in a tab.
2. In Canvas Downloader, click **Use the Canvas tab in my browser**.
3. Click the Canvas Downloader icon in the toolbar, then **Sign me in**.

The first time, Chrome asks whether the extension may use that site. Choose
**Allow**. Chrome closes the little window while it asks, which is normal and
handled: the sign-in finishes on its own and the icon shows a tick.

The icon shows a blue dot whenever the app is waiting for a sign-in, so you can
see when step 3 is the thing to do.

When it works, you get **"You are signed in"**, a five-second countdown, and
then a clean screen with nothing on it but the fact. One link takes you back to
the steps if something looks wrong.

## What it reads, and what it does not

Reads, for the tab you invoked it on, and only when you click:

- `canvas_session` (or `_normandy_session` on a self-hosted Canvas)
- `_csrf_token`, which Canvas requires alongside the sign-in before it will
  create the long-lived key that means you stop having to do this

**The stated reason for the second one used to be wrong, and it is worth knowing
why it was kept anyway.** This file claimed it "saves a round trip". It does not:
`core/token_mint.mint` always makes the one HTML request it describes, and reads
the token back out of the jar afterwards. But that jar is the one
`_session_for` has already installed the handed-over cookies into, so if Canvas
does not re-set `_csrf_token` on that request, the value the extension supplied
is the one that gets used. **Whether Canvas re-sets it has not been measured**,
and dropping the cookie on that reasoning would risk breaking the long-lived key
on the extension route specifically, which is the one route where nothing else
can supply it. Measure it against a real Canvas first: sign in through the
extension, and check whether the response to `GET /profile/settings` carries a
`Set-Cookie: _csrf_token`. If it does, this cookie can go, and the privacy
surface gets smaller for free.

It is never stored either way: `CanvasCredential.to_storable` keeps only the
session cookie, so nothing but the session cookie is ever written to disk.

It does **not** read anything else, does not run on any page, has no content
script, and holds no site access until you grant it. It posts to `127.0.0.1`
and nowhere else. Nothing is ever sent to the developer.

### It cannot see your browsing, by construction

The permission list is `cookies`, `activeTab`, `storage` and `alarms`. None of
them can tell the extension which sites you visit:

- there is **no `tabs` permission**, so it is never told what you have open;
- `activeTab` gives it the one tab you invoked it on, at the moment you invoke
  it, and nothing else;
- the once-a-minute alarm asks **one question of one address on your own
  machine**: is Canvas Downloader waiting for a sign-in? That is what lights
  the icon. It is not a question about you, and the browser is not involved.

A test in `tests/test_handoff.py` fails the build if `tabs`, `webNavigation`,
`history`, `browsingData` or a content script is ever added.

## How the app protects the connection

The app's listener is not a standing fixture. It:

- binds to `127.0.0.1` only, so nothing off your machine can reach it;
- opens only when you press the button, closes on the first sign-in it
  accepts, and times out after three minutes;
- **accepts requests only from a browser extension.** A web page cannot set its
  own `Origin` header, so a page on the internet cannot pretend to be one;
- returns nothing readable to a web page even if one did post to it;
- **checks the sign-in with Canvas and then shows you whose account it is**, so
  a sign-in that is not yours is visible rather than silent.

## Notes for whoever works on this next

**`canvas-hosts.js` is generated.** Run `python scripts/build_extension_hosts.py`
after the institution list changes; `--check` fails when it is stale, and a
test runs that check. It carries only the 100 Canvas hosts that a
`.instructure.com` suffix and the word `canvas` do not already recognise, out of
4,757 known schools.

**The work lives in `background.js`, not in the popup, and that is not a
preference.** `chrome.permissions.request()` opens a Chrome-owned prompt, the
popup loses focus, and a popup that loses focus is destroyed: the promise it was
awaiting never resolves and the code after it never runs. Measured on
2026-09-12, the first click did nothing and the second worked, because by then
the permission was already held and no prompt appeared. The service worker
survives, and `chrome.permissions.onAdded` is what lets the first attempt
finish.

**The copy is tested.** Developer wording is banned from anything a student can
read: no "session", "cookie", "token", "origin", "host", "port", "handoff" and
so on. `test_no_DEVELOPER_WORDING_reaches_the_student` fails the build on each
of them, and it has a positive control.

**The extension cannot ask whether the app is signed in, so it REMEMBERS.** The
app's listener closes the moment it accepts a sign-in, so seconds after
succeeding there is nothing to ping and the honest reading of that silence is
"not running" - which is what a student was shown right after it worked. The
extension does not need to ask: it performed the sign-in, and records that in
`chrome.storage.session`. A LIVE request for a sign-in always beats the memory,
so a stale one can never hide a screen somebody needs. Section 8 of
`tests/test_handoff.py`.

**If the popup reports the app as closed while the app is plainly open**, check
for more than one listener: `python scripts/check_handoff.py` now fails when
several ports answer. Running from source, any edit to an app file makes
Streamlit re-import its modules, and a listener opened by a previous
incarnation used to stay up with nothing able to close it - so the extension
reached an ORPHAN that accepted the sign-in into state the app could not read.
Fixed (the listener lives in a module a watcher cannot unload), but the checker
keeps the guard because the symptom is three separate "it worked" signals and a
failure.
