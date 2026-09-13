/*
 * The part that has to outlive the popup.
 *
 * THE BUG THIS EXISTS FOR, measured by the product owner on 2026-09-12:
 * "first time i clicked on the button in the extension... google chrome asked
 * for a permission, after which nothing happened in neither the extension or
 * canvas downloader. Then i waited 5 minutes and tried again - that time... it
 * logged in."
 *
 * That is not a race and it is not the app. `chrome.permissions.request()`
 * opens a Chrome-owned prompt, the popup loses focus, and **a popup that loses
 * focus is destroyed** - so the promise the popup was awaiting never resolves
 * and the code after it never runs. The second attempt works because the
 * permission is already held by then, so `request()` resolves instantly with no
 * prompt and the popup survives.
 *
 * So the work cannot live in the popup. A service worker is not torn down by a
 * focus change, and `chrome.permissions.onAdded` fires here - which is exactly
 * the signal that the first attempt was missing. The popup now only decides
 * WHAT to do; this file does it, and survives to finish.
 *
 * WHAT THIS NEVER DOES
 * --------------------
 * It has no access to your browsing. There is no `tabs` permission, no content
 * script and no host permission held at install time. The once-a-minute alarm
 * below asks ONE question of ONE address on this machine - "is Canvas
 * Downloader waiting for a sign-in?" - and nothing else.
 *
 * The ONE site it can see is the one you granted it, and that boundary is
 * Chrome's rather than ours: without the `tabs` permission Chrome redacts
 * `tab.url` for every origin an extension holds no host permission for. So
 * when the icon lights up on your Canvas it is because you granted this
 * extension that origin for your own sign-in - and every other tab you open is
 * literally unreadable to it. `refreshBadge` below checks the permission
 * explicitly as well, so the rule is stated in this file and not merely
 * inherited.
 */

/** Ports the app listens on. Mirrors core/handoff.py PORTS; a test pins them. */
const PORTS = [53127, 53128, 53129];

/** The only cookies ever read. Mirrors core/handoff.py ACCEPTED_COOKIES. */
const WANTED = ["canvas_session", "_normandy_session", "_csrf_token"];
const SESSION = ["canvas_session", "_normandy_session"];

/** How often to ask whether the app is waiting, so the icon can say so. */
const POLL_MINUTES = 1;

const BADGE_READY = "•";          // a dot, not a count: there is nothing to count

// ── talking to the app ──────────────────────────────────────────────────────

/**
 * How long to wait for one port before giving up on it.
 *
 * A closed port refuses instantly, so this only ever matters when something
 * ACCEPTS the connection and then says nothing - another program holding the
 * port, a stalled app. Without it that `fetch` never settles, `findApp` never
 * returns, the popup's status request is never answered, and the popup sits on
 * "Checking" for ever. Reported exactly that way on 2026-09-12.
 */
const PING_TIMEOUT_MS = 1200;

/** The app's port and whether it is waiting, or null if it is not running. */
async function findApp() {
  for (const port of PORTS) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/ping`, {
        method: "GET",
        credentials: "omit",
        cache: "no-store",
        signal: AbortSignal.timeout(PING_TIMEOUT_MS),
      });
      if (!r.ok) continue;
      const body = await r.json();
      if (body && body.app === "canvas-downloader") {
        return { port, waiting: !!body.waiting };
      }
    } catch (e) {
      /* Nothing listening on this port. Try the next. */
    }
  }
  return null;
}

/**
 * Read the Canvas sign-in for `origin` and hand it to the app.
 *
 * Answers a plain result object the popup can render. Never throws: every
 * failure here is something a student has to be told in their own words.
 */
async function connect(origin, host) {
  const app = await findApp();
  if (!app) {
    return { ok: false, code: "no_app" };
  }
  if (!app.waiting) {
    return { ok: false, code: "not_waiting" };
  }

  let cookies = [];
  try {
    // An extension can read httpOnly cookies, which the Canvas one is. That is
    // the whole reason this route exists: a web page could never do it.
    cookies = await chrome.cookies.getAll({ url: origin });
  } catch (e) {
    return { ok: false, code: "no_permission" };
  }

  const picked = {};
  for (const c of cookies) {
    if (WANTED.includes(c.name) && c.value) picked[c.name] = c.value;
  }
  if (!SESSION.some((n) => picked[n])) {
    return { ok: false, code: "not_signed_in" };
  }

  try {
    const r = await fetch(`http://127.0.0.1:${app.port}/canvas-session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "omit",
      body: JSON.stringify({ host, cookies: picked }),
      // Bounded for the same reason as the ping: a socket that accepts and
      // then says nothing must not leave the student watching a spinner.
      signal: AbortSignal.timeout(8000),
    });
    if (r.ok) return { ok: true, host };
    const body = await r.json().catch(() => ({}));
    return { ok: false, code: "refused", detail: body.error || String(r.status) };
  } catch (e) {
    return { ok: false, code: "unreachable" };
  }
}

// ── the pending handover, which is what survives the prompt ─────────────────

async function setPending(target) {
  await chrome.storage.session.set({ pending: target });
}

async function takePending() {
  const { pending } = await chrome.storage.session.get("pending");
  await chrome.storage.session.remove("pending");
  return pending || null;
}

async function setResult(result) {
  await chrome.storage.session.set({
    lastResult: { ...result, at: Date.now() },
  });
  if (result && result.ok) await rememberSignedIn(result.host);
}

/**
 * THE APP CANNOT BE ASKED WHETHER IT IS SIGNED IN, so remember that we did it.
 *
 * Measured in `core/handoff.py`: accepting a sign-in sets `open = False` and
 * `ui/auth.py` then calls `handoff.stop()`, which closes the socket. Seconds
 * after a SUCCESSFUL sign-in, therefore, `/ping` answers nothing at all and the
 * honest reading of that silence is "not running" - which is what the student
 * was shown, right after the thing worked.
 *
 * The extension does not need to ask. IT PERFORMED THE SIGN-IN; that is its own
 * fact, and this is where it is kept. `chrome.storage.session` is the right
 * lifetime: it lives until the browser closes and never touches the disk, so
 * the memory cannot outlive the browsing it belongs to.
 *
 * A LIVE REQUEST ALWAYS BEATS THE MEMORY - if the app is asking for a sign-in
 * now, the popup shows the guide no matter what this says. So a stale memory
 * can never stand between a student and the screen they need.
 */
async function rememberSignedIn(host) {
  await chrome.storage.session.set({
    signedIn: { host: host || "", at: Date.now() },
  });
}

/**
 * Granting the permission is the LAST thing the first attempt managed to do.
 * Picking it up here is what makes that attempt finish instead of dying.
 */
chrome.permissions.onAdded.addListener(async () => {
  const pending = await takePending();
  if (!pending || !pending.origin) return;
  const result = await connect(pending.origin, pending.host);
  await setResult(result);
  await refreshBadge();
  if (result.ok) {
    // The popup is gone, so the only place left to say so is the icon.
    chrome.action.setBadgeText({ text: "✓" });
    chrome.action.setBadgeBackgroundColor({ color: "#1f7a5c" });
    setTimeout(() => refreshBadge(), 8000);
  }
});

// ── messages from the popup ────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || typeof msg !== "object") return false;

  if (msg.type === "connect") {
    connect(msg.origin, msg.host).then(async (result) => {
      await setResult(result);
      await refreshBadge();
      sendResponse(result);
    });
    return true;                       // keep the channel open for the await
  }

  if (msg.type === "pending") {
    setPending({ origin: msg.origin, host: msg.host }).then(() =>
      sendResponse({ ok: true })
    );
    return true;
  }

  if (msg.type === "status") {
    findApp().then((app) => {
      sendResponse({ app });
      // Answer first, then repaint. The badge was otherwise only refreshed by
      // a once-a-minute alarm, so a student who armed the sign-in and opened
      // this straight away met an icon that still said nothing was happening -
      // reported 2026-09-13 as the icon not showing it had recognised
      // anything. Through `refreshBadge` rather than painting from `app`
      // alone, so the "only on a granted Canvas tab" rule is applied in ONE
      // place and this path cannot drift away from it.
      refreshBadge();
    });
    return true;
  }

  return false;
});

// ── the icon, which is the only thing that can say "now" ───────────────────

/**
 * Show a dot on the icon while the app is waiting for a sign-in.
 *
 * This is the whole of the "tell me when to click" feature, and it is
 * deliberately the smallest thing that could deliver it. It asks the app, on
 * this machine, whether it is waiting. It does not ask the browser anything,
 * so there is no version of this that knows which sites you are on.
 */
/** Paint the icon from an answer already in hand. Asks the app nothing. */
async function paintBadge(ready) {
  await chrome.action.setBadgeText({ text: ready ? BADGE_READY : "" });
  if (ready) {
    await chrome.action.setBadgeBackgroundColor({ color: "#0072CE" });
    await chrome.action.setTitle({
      title: "Canvas Downloader is ready - click to sign in",
    });
  } else {
    await chrome.action.setTitle({ title: "Sign in to Canvas Downloader" });
  }
}

/**
 * Is the tab in front of the student a Canvas we were GRANTED access to?
 *
 * This is how the icon can react to Canvas without the extension ever learning
 * where else you go. There is no `tabs` permission and no content script, so
 * Chrome REDACTS `tab.url` for every site we hold no host permission for - the
 * only origin we can see is the one the student granted for their own sign-in.
 * The permission check below is explicit rather than relying on that redaction
 * alone, so the rule is auditable in this file instead of implied.
 */
async function onGrantedCanvasTab() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url || !/^https?:/i.test(tab.url)) return false;
    const origin = new URL(tab.url).origin;
    return await chrome.permissions.contains({ origins: [`${origin}/*`] });
  } catch (e) {
    return false;                      // unknown is NOT "yes"
  }
}

/**
 * The icon lights at ONE moment: the app is asking for a sign-in AND the
 * student is looking at their Canvas. That is precisely "click me now".
 *
 * Chosen by the product owner on 2026-09-13 over a mark that shows on every
 * Canvas page, and for his own earlier reason: an icon lit during ordinary
 * Canvas use reads as "this thing is on and watching me", which is how an
 * extension gets uninstalled. Blank the rest of the time is the honest look,
 * because the rest of the time there is nothing to do.
 */
async function refreshBadge() {
  if (!(await onGrantedCanvasTab())) return paintBadge(false);
  const app = await findApp();
  await paintBadge(!!(app && app.waiting));
}

// Re-evaluate when the student changes what they are looking at. Neither event
// is told a URL we have no permission for, so this cannot become a history.
chrome.tabs.onActivated.addListener(() => refreshBadge());
chrome.tabs.onUpdated.addListener((_id, change, tab) => {
  if (tab && tab.active && (change.status === "complete" || change.url)) {
    refreshBadge();
  }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: POLL_MINUTES });
  refreshBadge();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: POLL_MINUTES });
  refreshBadge();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "poll") refreshBadge();
});
