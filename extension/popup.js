/*
 * The popup decides WHAT should happen and says so in a student's words.
 * `background.js` does it, because this document does not survive Chrome's
 * permission prompt (see that file's header for the measurement).
 *
 * COPY RULES, set by the product owner on 2026-09-12 and binding:
 * no developer wording. Not "session", not "cookie", not "token", not "origin",
 * not "host", not "localhost", not "handoff", not "send". A student who is bad
 * with computers has to be able to read every line here and know what to do.
 * `tests/test_handoff.py` fails the build on the banned words.
 *
 * The screen is a three-step guide that KNOWS which step you are on, so the
 * thing you have to do next is the only thing emphasised.
 */

import { isCanvasHost } from "./canvas-hosts.js";

const els = {
  step1: document.getElementById("step1"),
  step2: document.getElementById("step2"),
  step3: document.getElementById("step3"),
  card: document.getElementById("card"),
  title: document.getElementById("cardTitle"),
  body: document.getElementById("cardBody"),
  go: document.getElementById("go"),
  foot: document.getElementById("foot"),
  appState: document.getElementById("appstate"),
  appText: document.getElementById("appText"),
  recheck: document.getElementById("recheck"),
  count: document.getElementById("countdown"),
  countNum: document.getElementById("countNum"),
  restTitle: document.getElementById("restTitle"),
  restBody: document.getElementById("restBody"),
  again: document.getElementById("again"),
};

/** Current target, filled in by `read()`. */
let target = null;      // { origin, host }
let needsPermission = false;
/** Cancels the countdown if the student does something first. */
let countdownTimer = null;
/** What the big button does on a screen that is not the sign-in itself. */
let goAction = null;

// ── rendering ──────────────────────────────────────────────────────────────

const CHECK_SVG = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';

function setSteps(current) {
  // `current === 0` means "no step is actionable yet", which is the honest
  // answer when Canvas Downloader is not running: none of these three steps
  // can help until it is. Reported 2026-09-13 - step 1 was highlighted with
  // the app off, "which would amount to nothing or have no purpose".
  [els.step1, els.step2, els.step3].forEach((el, i) => {
    const n = i + 1;
    const done = current > 3 || n < current;
    el.classList.toggle("done", done);
    el.classList.toggle("now", n === current);
    const dot = el.querySelector(".dot");
    if (done) {
      dot.innerHTML = CHECK_SVG;
    } else {
      dot.textContent = String(n);
    }
  });
}

/**
 * One render for every state. `tone` drives colour only, never meaning: the
 * sentence has to make sense read aloud with no colour at all.
 */
function show({ step, tone, title, body, site, button, enabled, spin, action }) {
  goAction = action || null;
  setSteps(step);
  els.card.className = "card" + (tone ? " " + tone : "");
  els.title.innerHTML = (spin ? '<span class="spin"></span>' : "") + title;
  els.body.textContent = body;
  if (site) {
    const s = document.createElement("span");
    s.className = "site";
    s.textContent = site;
    els.body.appendChild(s);
  }
  // A screen with nothing to press shows no button at all. A disabled one is
  // still the biggest, heaviest thing on the screen, and on the finished screen
  // it was drawing the eye to the one element that does nothing.
  // Leaving `button` out of a screen that cannot be pressed counts too: only
  // `null` used to hide it, so every "go and do this first" screen still showed
  // a grey "Sign me in" slab (seen in Chrome 155, 2026-10-22). A screen that
  // names its own label, like "Signing you in", keeps it as a progress line.
  els.go.hidden = button === null || (!button && !enabled);
  els.go.textContent = button || "Sign me in";
  els.go.disabled = !enabled;
  els.go.classList.toggle("ghost", button === "Allow access");
}

// ── the resting screen, for when there is nothing to do ────────────────────

/**
 * No guide, no steps, no button: just the fact, and a way back to the guide.
 *
 * The product owner's words on 2026-09-13: "when the user isn't on the login
 * screen in canvas downloader anymore... Should instead be a clean (no
 * steps/walkthrough) 'Canvas Downloader is logged in and running' with the
 * logo and a green dot".
 *
 * TWO SENTENCES, because there are two things we can know. Whether the app has
 * our sign-in is remembered from doing it. Whether it is running RIGHT NOW can
 * only be seen when it happens to be listening, which it mostly is not, so the
 * second half of the claim is only made when it was actually observed. Saying
 * "and running" on a guess would be the same lie as "not running" was.
 */
function showRest(running) {
  stopCountdown();
  document.body.classList.add("resting");
  els.restTitle.textContent = running
    ? "Canvas Downloader is signed in and running"
    : "Canvas Downloader is signed in";
  els.restBody.textContent = running
    ? "Nothing to do here. Carry on in the app."
    : "Nothing to do here. Your Canvas login has already been handed over.";
}

function leaveRest() {
  document.body.classList.remove("resting");
}

// ── the countdown, which is the transition ─────────────────────────────────

/**
 * How long the finished screen is held before it settles into the resting one.
 *
 * Asked for by the product owner on 2026-09-13: a success message "and then mb
 * a countdown from 5 or something to make the transition to the step 0 state
 * smooth". A number rather than a bar on purpose: this laptop has Windows
 * animation effects turned off, which is what made the first spinner look
 * broken, and a counting number is content, so it keeps working there.
 */
const DONE_SECONDS = 5;

function stopCountdown() {
  if (countdownTimer !== null) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
  els.count.hidden = true;
}

/** Show the finished screen, then hand over to the resting one. */
async function showDone() {
  stopCountdown();
  leaveRest();
  show({
    step: 4, tone: "good", title: "You are signed in",
    body: "Canvas Downloader has what it needs and is already loading your "
        + "courses. You can go back to the app.",
    button: null, enabled: false,
  });

  // Asked once, here, so the resting screen can be specific. The countdown is
  // five seconds and this is bounded well inside that.
  const status = await ask({ type: "status" });
  const running = !!(status && status.app);

  let left = DONE_SECONDS;
  els.countNum.textContent = String(left);
  els.count.hidden = false;
  countdownTimer = setInterval(() => {
    left -= 1;
    if (left <= 0) {
      stopCountdown();
      showRest(running);
      return;
    }
    els.countNum.textContent = String(left);
  }, 1000);
}

// ── what the app says ──────────────────────────────────────────────────────

/**
 * Ask the worker something. ALWAYS settles.
 *
 * The product owner reported the popup stuck on "Checking / One moment"
 * (2026-09-12). A popup that can hang is a popup that tells the student
 * nothing, so both ends are now bounded: the worker's `fetch` calls carry an
 * abort signal, and this refuses to wait past `ASK_TIMEOUT_MS` even if the
 * worker never answers at all - which can happen if it failed to start.
 */
const ASK_TIMEOUT_MS = 4000;

/**
 * The sign-in itself gets longer, because the worker's own bounds add up to
 * more than `ASK_TIMEOUT_MS`: one ping round (1.2 s) and then the handover
 * (8 s). With the short deadline a slow but successful sign-in was reported to
 * the student as "Could not reach Canvas Downloader" while it was still going.
 */
const CONNECT_TIMEOUT_MS = 12000;

function ask(message, timeoutMs = ASK_TIMEOUT_MS) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const timer = setTimeout(() => done(null), timeoutMs);
    try {
      chrome.runtime.sendMessage(message, (reply) => {
        clearTimeout(timer);
        if (chrome.runtime.lastError) return done(null);
        done(reply || null);
      });
    } catch (e) {
      clearTimeout(timer);
      done(null);
    }
  });
}

/**
 * The on/off line, which is the first thing the student should be able to read.
 *
 * Three real states, not two: the app can be running and simply not asking for
 * a sign-in yet, and telling somebody "not running" then would be a lie that
 * sends them looking for the wrong problem.
 */
function showAppState(app, known = true) {
  const on = !!app;
  const ready = !!(app && app.waiting);
  els.appState.className = "appstate " + (ready ? "on" : on ? "armed" : "off");
  // NOT KNOWING IS ITS OWN STATE. When the extension's own background part
  // gives no answer, nothing was learned about the app, and "Not running"
  // would send the student to restart a program that may be fine.
  els.appText.textContent = !known
    ? "Could not check"
    : !on
      ? "Not running"
      : ready
        ? "Running, ready to log in"
        : "Running, sign-in not started";
}

// ── the screen for when this popup itself went wrong ───────────────────────

/**
 * Shown instead of "Checking" staying up for ever.
 *
 * Measured 2026-10-22 in Chrome 155: one Chrome call that failed inside
 * `read()` left the popup on "Checking / One moment" with no way out, because
 * nothing caught it. Every way into `read()` now goes through `guarded`, so a
 * failure always ends on a screen with something to press.
 */
function showStuck() {
  stopCountdown();
  leaveRest();
  showAppState(null, false);
  show({
    step: 0, tone: "bad", title: "Something got stuck",
    body: "Click Try again. If this keeps happening, close Chrome completely "
        + "and open it again.",
    button: "Try again", enabled: true, action: () => read(),
  });
}

/** Longest a check may take before the student is told and offered a way on. */
const READ_DEADLINE_MS = 8000;

/** Run a screen-deciding step so that it can only end on a real screen. */
async function guarded(fn) {
  let timer = null;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("no answer in time")),
      READ_DEADLINE_MS);
  });
  try {
    await Promise.race([fn(), deadline]);
  } catch (e) {
    console.warn("Canvas Downloader: the popup could not finish checking", e);
    showStuck();
  } finally {
    clearTimeout(timer);
  }
}

// ── working out where we are ───────────────────────────────────────────────

async function read() {
  stopCountdown();
  leaveRest();

  // 0. Is the app on at all? FIRST, and unconditionally, because when it is
  // off there is nothing this extension can do for the student and that is
  // the single most useful thing the screen can tell them. Reported as a gap
  // on 2026-09-12: the wrong-page screen said nothing about the app.
  const status = await ask({ type: "status" });
  // `null` is the extension's own background part not answering at all, which
  // says nothing about the app - so it is not reported as "not running".
  if (status === null) return showStuck();
  const app = status.app;
  showAppState(app);

  // 0b. Already done? A LIVE REQUEST FOR A SIGN-IN ALWAYS WINS, so this is
  // only consulted when the app is not asking for one. Everything below is a
  // three-step guide towards a sign-in that has already happened, and showing
  // it would send the student to redo finished work.
  if (!(app && app.waiting)) {
    const { signedIn } = await chrome.storage.session.get("signedIn");
    if (signedIn) return showRest(!!app);
  }

  // 0c. The app is off: that comes before anything about the tab. It used to
  // be checked after, so a student on any other page was told to "Open your
  // Canvas page first" - and did, and was then told the app was not open.
  // With the app off, opening it is the next thing to do wherever they are.
  if (!app) {
    return show({
      step: 0, tone: "warn",
      title: "Canvas Downloader is not open",
      body: "Open the Canvas Downloader app on this computer and choose "
          + "“Sign in with the extension”. Then open this extension again.",
      enabled: false,
    });
  }

  // 1. Which tab is the student looking at?
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !/^https?:/i.test(tab.url)) {
    return show({
      step: 1, tone: "warn",
      title: "Open your Canvas page first",
      body: "Go to the tab where you use Canvas, then open this extension again.",
      enabled: false,
    });
  }

  let url;
  try {
    url = new URL(tab.url);
  } catch (e) {
    return show({
      step: 1, tone: "warn",
      title: "Open your Canvas page first",
      body: "This tab is not a web page. Switch to your Canvas tab and try again.",
      enabled: false,
    });
  }
  target = { origin: url.origin, host: url.host };

  // 2. Is it Canvas? Recognised from the app's own list of 4,757 schools.
  if (!isCanvasHost(url.host)) {
    return show({
      step: 1, tone: "warn",
      title: "This does not look like Canvas",
      body: "Switch to the tab where your school's Canvas is open, then open "
          + "this extension again. You are currently on:",
      site: url.host,
      enabled: false,
    });
  }

  // 3. The app's answer, already in hand from step 0.
  if (!app.waiting) {
    return show({
      step: 2, tone: "warn",
      title: "Nearly there",
      body: "In Canvas Downloader, click “Sign in with the "
          + "extension”. Then come straight back here.",
      enabled: false,
    });
  }

  // 4. Does Chrome already let us read this site?
  needsPermission = !(await chrome.permissions.contains({
    origins: [`${url.origin}/*`],
  }));

  if (needsPermission) {
    const infoSvg = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="flex:0 0 15px;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
    return show({
      step: 3, tone: "info",
      title: infoSvg + "One-time approval",
      body: "Chrome will ask if Canvas Downloader may use this page. Choose "
          + "Allow. This little window closes when it asks. That is "
          + "normal, and you do not have to do anything else.",
      site: url.host,
      button: "Allow access",
      enabled: true,
    });
  }

  show({
    step: 3, tone: "good",
    title: "Ready on " + url.host,
    body: "Click below and Canvas Downloader signs you in. Nothing to type.",
    enabled: true,
  });
}

// ── the one action ─────────────────────────────────────────────────────────

const MESSAGES = {
  no_app: "Canvas Downloader closed. Open it again and try once more.",
  not_waiting:
    "Canvas Downloader stopped waiting. In the app, click “Sign in with the "
    + "extension”, then come back.",
  no_permission:
    "Chrome did not let this page be used. Click again and choose Allow.",
  not_signed_in:
    "You are not signed in to Canvas on this tab. Sign in to Canvas here "
    + "first, then try again.",
  refused: "Canvas Downloader could not use this. Try signing in to Canvas "
    + "again on this tab.",
  unreachable: "Could not reach Canvas Downloader. Is it still open?",
};

els.go.addEventListener("click", async () => {
  if (goAction) return guarded(goAction);
  if (!target) return;

  if (needsPermission) {
    // Tell the worker what to finish BEFORE asking, because this document is
    // about to be destroyed by the prompt. The worker picks it up from
    // `permissions.onAdded` and completes the sign-in without us.
    await ask({ type: "pending", origin: target.origin, host: target.host });
    els.go.disabled = true;
    try {
      await chrome.permissions.request({
        origins: [`${target.origin}/*`],
      });
    } catch (e) {
      /* The popup usually dies before this resolves. That is the point. */
    }
    // If we are somehow still alive, carry on normally.
    await guarded(read);
    return;
  }

  show({
    step: 3, tone: null, title: "Signing you in", spin: true,
    body: "One moment.", button: "Signing you in", enabled: false,
  });

  const result = await ask({
    type: "connect", origin: target.origin, host: target.host,
  }, CONNECT_TIMEOUT_MS);

  if (result && result.ok) {
    // Do NOT close the popup here. It used to shut itself after 2.2 seconds,
    // which threw away the only confirmation the student ever gets: the app
    // has no way to tell the extension it is signed in, so this screen is it.
    await showDone();
    return;
  }

  const code = (result && result.code) || "unreachable";
  show({
    step: 3, tone: "bad", title: "That did not work",
    body: MESSAGES[code] || MESSAGES.unreachable,
    button: "Try again", enabled: true,
  });
});

// ── checking again, because the app can start after this popup opened ──────

/**
 * The way out of the resting screen, and the only one.
 *
 * FORGETTING IS THE POINT. A student who clicks this is saying the remembered
 * sign-in is not matching what they see, so the memory has earned no more
 * trust and the guide is what they need. The next successful sign-in writes it
 * again, so nothing is lost for good.
 */
els.again.addEventListener("click", async () => {
  try {
    await chrome.storage.session.remove("signedIn");
  } catch (e) {
    /* Worst case the resting screen comes back next time. Still show the
       guide now, which is what was actually asked for. */
  }
  await guarded(read);
});

els.recheck.addEventListener("click", async () => {
  els.recheck.disabled = true;
  els.recheck.classList.add("spinning");
  els.appText.textContent = "Looking for Canvas Downloader";
  els.appState.className = "appstate off";
  try {
    await guarded(read);
  } finally {
    els.recheck.disabled = false;
    els.recheck.classList.remove("spinning");
  }
});

els.foot.addEventListener("click", () => {
  els.foot.classList.toggle("expanded");
});

// ── on open, including straight after the prompt killed us ─────────────────

guarded(async function start() {
  // If the worker finished a sign-in while this popup was closed, say so
  // instead of starting the guide over. Without this, the student reopens the
  // popup after granting and is told to do something that already happened.
  const { lastResult } = await chrome.storage.session.get("lastResult");
  if (lastResult && Date.now() - lastResult.at < 20000) {
    await chrome.storage.session.remove("lastResult");
    if (lastResult.ok) {
      // This is the path after Chrome's approval prompt destroyed the popup
      // mid-sign-in, so it is the FIRST time this student sees that it
      // worked. Same finished screen, same countdown, same landing.
      return showDone();
    }
  }
  await read();
});
