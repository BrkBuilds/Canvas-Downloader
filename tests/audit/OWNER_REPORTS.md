# Owner reports: defects seen in real use

Defects the product owner hit while USING the app on his own machines, written
down in the session they were reported. Kept separate from `AUDIT_FINDINGS.md`
on purpose: that file is written and re-fingerprinted by the live-audit harness
on every run, and a hand-written entry in it would either be clobbered or read
back as a harness finding. Nothing here came from a harness. Every entry says
what was CONFIRMED by reading the code and what is still a HYPOTHESIS awaiting a
repro, because this repo's rule is that an unreproduced cause is a pointer, not a
diagnosis.

Status vocabulary matches `AUDIT_FINDINGS.md`: `open`, `fixed`, `accepted`,
`wontfix`, `invalid`.

---

## Reported 2026-09-07, during the Store rename work

All four were reported together, and all four were **deliberately excluded from
v2.0.3**. That release exists only to make the MSIX `DisplayName` match the Store
listing name, under a certification deadline of 14 September. Bundling UI or auth
changes into the submission that has to pass would put the deadline at risk for
defects that are already live in 2.0.2 and make nothing worse by waiting. They
are the 2.0.4 list.

---

### 1. "See configuration" on Quick Download does not reflect what was chosen

**Status**: open
**Severity**: low
**Reported**: 2026-09-07, owner, from ordinary use
**Reproduced by Claude**: no

**Detail**: The `See configuration` expander on the Quick Download page shows a
configuration that does not match what the user selected on that same page.

**Where to look**: `ui/quick_download.py:1082` renders
`st.expander("See configuration")`. The badge markup is
`shared/components.py:3606` `render_config_summary_badges(settings, show_path)`,
and the Panopto column of it is fed through
`panopto/settings.py:518` `contract_to_ui_keys(contract)`.

**The question to ask first**, because it decides the whole shape of the fix: is
the panel reading the SAME settings dict the run will execute, or a preset
default that the page's own controls have since overridden? A summary built from
a different source than the executor is not a rendering bug, it is two sources of
truth, which is the defect class CLAUDE.md names first.

---

### 2. Custom Download: "See configuration" and "Change folder" get swallowed into the download phase card

**Status**: open
**Severity**: medium (cosmetic, but persistent and highly visible)
**Reported**: 2026-09-07, owner, seen once on his own PC
**Reproduced by Claude**: no

**Detail**: On Custom Download, after interacting with `Change folder` and
`See configuration` and then pressing the download button quickly, both elements
were absorbed INTO the download phase card, rendered underneath the live log and
greyed out. **There were no reruns during the download, so they never went away**
for the whole run.

**This is almost certainly the known Streamlit index-reconciliation family, not a
new bug.** The repository already documents the mechanism three times: a keyed
card is inherited by whatever element lands on its index, `addBlock` REUSES the
children of the block it replaces, and a container replacement that is not
isomorphic hands its slot to a sibling. See `.claude/rules/streamlit-ui.md` and
the completion-card entries. The distinguishing symptom here is the same one
those entries describe: the wrong parent adopts live children, and greying is the
new parent's styling applied to nodes that were never its own.

**Why the timing matters**: pressing download quickly is what makes the phase
card appear in the same run as elements the page had just mutated. That is the
race, and it is why it is hard to hit twice.

**Do not fix this by converting the elements to `st.empty()` or a fresh
container.** Both are recorded as the wrong tool inside a list-shaped region and
one of them caused a whole-page blank flash. Reproduce first, then count slots
and children.

---

### 3. Panopto switched OFF still produces a failure expander on the success screen

**Status**: open
**Severity**: low, but it is the one that annoys the owner most
**Reported**: 2026-09-07, owner
**Reproduced by Claude**: no

**Detail**: With Panopto switched off in Settings, downloading a course that has
Panopto content still shows a *"couldn't download panopto lecture recordings"*
expander on the SUCCESS completion screen. Nothing failed. The user turned the
feature off on purpose, so a failure panel is both wrong and irritating.

**The polite panel already exists and is already wired**, which is why this reads
as a duplicate rather than a missing feature.
`shared/components.py:2694` `render_panopto_disabled_notice()` is the third
member of the "deliberately left alone" family (size-skipped files, unpacked
archives): a quiet skip-panel that says recordings were not fetched because the
switch is off. It is called from `app.py:2804` for download mode and
`sync/completion.py:255` for sync mode, and it returns early when the switch is
on. That is exactly the "less invasive" treatment the owner asked for, and it is
shipped.

**HYPOTHESIS, not confirmed**: the generic failed-files expander at
`shared/components.py:2148` (*"We couldn't download these files after
retrying."*) is a SEPARATE panel, and Panopto or LTI media items are still
landing in its list even when the switch is off, so both panels render. The
category label `'LTI/Media Stream'` at `shared/components.py:1670` is where such
an item would be classified.

**The repro to run**: switch Panopto off, download one known Panopto course, and
capture the completion screen. If BOTH panels are present, the fix is to stop
filing Panopto/LTI items as failures when the switch is off, not to add another
notice. If only the failure panel is present, the disabled notice is being
suppressed and the question is why `panopto_disabled_courses(mode)` returned
empty.

---

### 4. Today's files runs on a session that was never CONFIRMED, and reports one amber notice per course

**Status**: open
**Severity**: medium, and it is the one with real user impact
**Reported**: 2026-09-07, owner, from two separate incidents on two machines
**Root cause**: CONFIRMED by reading, on the auto-sync precondition. The second
incident's classification step is still a hypothesis.

**The two incidents**

- **Slow laptop, wifi still connecting** (2026-09-05). Daily auto-sync fired
  correctly, then produced a cascade of amber notices, one after another. Once
  wifi came up the app recovered and downloaded.
- **Revoked token, good internet** (2026-09-07). The app went straight into
  Today's files and started searching for files to download. Every course fetch
  failed and spawned its own amber notice under the search/download card.
  **His name was missing from the login area**, so the app already had evidence
  the token was dead before Today's began.

**CONFIRMED root cause**: `core/auto_sync.py:72` `should_auto_sync()` gates on
exactly three things - the auto-sync setting, `last_auto_sync_date` against
`logical_today()`, and `resolve_today_pairs()` being non-empty. **There is no
precondition on whether the saved session was actually confirmed against Canvas
this launch.**

**Why an unconfirmed session exists at all, and why that part is CORRECT**:
`ui/auth.py` restore calls `CanvasManager.validate_token()`. On success it sets
`is_authenticated` AND `user_name`. On failure it splits: `is_auth_error(msg)`
routes to the login page for a fresh token, and **anything else restores
OPTIMISTICALLY** - `is_authenticated = True`, `user_name` never set - so a
network blip does not strand a previously verified session behind a login wall.
The code documents this as *"the single most important robustness property of the
login path for users on unreliable or high-latency networks"*, and it is right.
Do not fix this by making restore pessimistic.

**The gap is that Today's auto-sync cannot tell the two apart**, and it is the
one caller that must, because it runs headless, immediately, once per course,
with a visible notice per failure. Incident 1 is that exact path.

**The discriminator already exists and costs nothing**: on the optimistic branch
`user_name` is never set, so `is_authenticated and not user_name` IS "signed in
but unconfirmed this launch". A named flag set at the two decision sites would be
cleaner than inferring it from a display string, and writing the verdict once is
this repo's standing rule.

**Still a hypothesis for incident 2**: with a genuinely revoked token on a good
connection, `is_auth_error(msg)` should have matched and sent him to the login
page. He landed in Today's instead, which is the optimistic branch, so either
that classifier did not recognise this revocation message or something else set
`is_authenticated`. **Reproduce by revoking a token and relaunching**, and read
what `validate_token()` actually returned before changing the classifier. A
classifier fixed against a guessed message is a classifier that still cannot say
no.

**Second, independent defect in the same report**: N failing courses produce N
amber notices. One notice for the run, naming the count, is the right shape, and
it is worth fixing even if the gating above lands, because a slow network can
still fail some courses mid-run.

---

## 2026-09-12: A DROPPED BROWSER CONNECTION RE-RAN THE WHOLE DOWNLOAD, TWICE

Reported as *"something happened when the panopto download was supposed to
start, where the mb tracker started from the beginning... files were at
total/total and percentage at 100% but ETA at 7 minutes remaining."* The debug
log (`C:\Users\birkl\Downloads\Ny mappe\debug_log.txt`, 69,124 lines, 4.7 MB)
settles it. **NOT reproduced deliberately yet; the mechanism below is read off
the log and the source, and the last step is a guess that needs driving.**

### What the log says, in order

| time | line |
|---|---|
| 23:22:11 | `=== Download Start: ... Course 1/1 ===` (the real one) |
| 23:27:57 | last `File Saved:` of that run. **83 files saved** |
| 23:31:59 | `--- Canvas Content Phase: [assignments, syllabus, ...] ---` |
| 23:32:04 | first `WebSocketClosedError` - the browser connection is gone |
| **23:32:19** | **`=== Download Start: ... Course 1/1 ===` AGAIN** |
| 23:34:18 | Canvas Content Phase again |
| **23:34:28** | **`=== Download Start: ... ===` a THIRD time** |
| 23:35:06 | `Download cancel event cleared (was set)` + 87 `StopException` (the
  product owner cancelling) |

**Three download starts from one click.** 83 files saved, **157
`Skipping existing file`** - the restarts re-walked what the first run had
already put on disk. 5,158 `WebSocketClosedError` tracebacks, every one of them
a UI update with nowhere to go.

### The mechanism, which is a split between two kinds of state

* **Navigation lives in QUERY PARAMS.** `_write_nav_to_query_params()` puts
  `?mode=download&step=3&quick=1` in the URL, and `_restore_nav_from_query_params()`
  reads it back at the top of `app.py`. Query params survive a reconnect,
  because they are in the URL.
* **Run state lives in `st.session_state`.** A closed websocket means the next
  connection is a NEW Streamlit session, and session state starts EMPTY.
* So on reconnect the two disagree: the URL says *"you are on the download
  step, in quick mode"* and the session says *"no download has ever been
  started here"* (`download_status` absent). Every "start it if it has not
  started" guard is written against `download_status`, so all of them pass, and
  the app scans and sets `download_status = 'running'` again.

That is also the whole of the user-visible nonsense: two runs writing the same
placeholders, so **100% complete with a 7-minute ETA** is one run's progress
bar next to another run's estimator.

### Why it matters more than it looks

* Bytes are bounded by the skip-existing check, but **only for files already on
  disk**. Anything the first run had not reached yet is fetched again, and the
  whole Canvas metadata walk is repeated.
* **The daily auto-sync runs unattended**, which is the case where nobody is
  watching a restart happen.
* **The debug log becomes useless.** 4.7 MB in which the app's own lines are
  0.4% of the file. This is the hazard `data-safety.md` already records for the
  Panopto progress hook ("an unconditional traceback would bury the run's real
  errors under hundreds of identical stacks") reaching a different subsystem -
  here it is Streamlit's own websocket writer, not app code, and nothing in the
  app rate-limits or suppresses it.
* **Panopto never ran**, which is what the report was actually about: the phase
  was restarted out from under itself before it could begin.

### What has NOT been established

* **Why the websocket closed at 23:32:04.** It is 5 seconds after the Canvas
  Content Phase began, which is suggestive and is not evidence. A backgrounded
  tab, a reload, a burst of ForwardMsgs and a Chrome throttle are all live
  candidates. **Do not fix the restart by guessing at the socket.**
* Whether a restart can also happen on the SYNC side, which has its own
  step/status model.
* Whether the packaged app behaves the same. This run was `python dev.py` in
  Chrome; the shipped app renders in WebView2, where a tab cannot be
  backgrounded the same way - so the trigger may be rarer there while the
  defect is identical.

### The shape of the fix, not yet written

The defect is not the closed socket, which is ordinary and must be survivable.
It is that **a side effect is re-triggered by state that does not know the side
effect already happened**. The reconnect is indistinguishable from a fresh
arrival because the only evidence lives in the session that died.

So the run has to be recorded somewhere PROCESS-GLOBAL, next to the other
process-global run state this app already keeps (`core/state_registry.py`,
`core/cancellation.py`) - a run identity that a new session can find and adopt
rather than re-create. A guard purely inside `st.session_state` cannot work, by
construction: that is the thing that was lost.

Needs its own reproduce (close the tab mid-download and reopen it), fix, test
and mutation pass. **Do not bolt it onto an unrelated change.**

## 2026-09-12: `Keyring delete_password failed: CanvasDownloader` on EVERY logout

Seen twice in one evening (23:08:03 and 23:41:22), both immediately on logout.
Benign, and the log line is not.

`keyring.errors.PasswordDeleteError` is what the Windows backend raises when
there is **nothing to delete**, and its message is just the service name -
which is why the line reads as though `CanvasDownloader` were the error. There
is often nothing to delete on this machine by design: a browser-login
credential serialises to about 3,260 bytes and Windows Credential Manager
refuses anything over 2,560, so the credential lives in the DPAPI fallback file
and the keyring entry never existed.

So a completely normal logout logs a WARNING that says a delete failed. That is
the wrong way round for the one action whose whole job is to leave nothing
behind: a real failure and an empty store have to be distinguishable, or nobody
can tell whether a logout on a shared machine actually cleared anything.
`_safe_keyring_delete` should treat "no such password" as success at debug
level and keep the warning for everything else.

---

## 2026-09-13: `got CanvasCredential` - a hot reload signed the user out, unrecoverably

Reported with the terminal output, repeating seven times:

```
TypeError: Canvas credential must be a CanvasCredential, str or None,
           got CanvasCredential
```

FIXED. The message reads like nonsense and is exactly right: there were **two
class objects with that name**. Streamlit's file watcher re-imports a changed
module and builds a new `CanvasCredential`, while `st.session_state['api_token']`
still holds an instance of the old one. `isinstance` compares identity, so it
answers False for two classes that are the same code.

- **The symptom was not a crash**, which is why it was so confusing.
  `core/course_cache.py` catches it (`Course refresh failed; keeping the cached
  list`), so the user met an **amber network/VPN error with a Try again button**
  and then *"Canvas sign-in did not finish"* - while holding a perfectly good
  credential. **Signing in again could not fix it**: the new credential landed in
  the same stale-typed slot, which is why repeated sign-ins through both routes,
  and a page refresh, all failed.
- **SOURCE RUNS ONLY.** `start.py` passes `--server.fileWatcherType=none` when
  frozen, so the shipped app has no watcher and cannot reach this. `python
  dev.py` and `python start.py` can. That is also why it appeared during a
  session in which files were being edited.
- `coerce()` now recognises a credential from a previous incarnation of the
  module and REBUILDS it, so what comes out is always an instance of the current
  class and nothing downstream can meet the mismatch again. Deliberately narrow:
  the name must match AND every field must be present, so a genuinely wrong type
  still fails loudly - which is the whole reason this is a distinct type rather
  than a `str` subclass.
- Covered by `test_a_credential_from_a_RELOADED_module_is_adopted`, which builds
  a REAL second incarnation through `importlib` rather than a hand-made
  lookalike, and asserts `not isinstance(...)` first so the test cannot pass
  without reproducing the failure. Its positive control
  (`test_a_GENUINELY_wrong_type_still_fails_loudly`) pins the narrowness.

## 2026-09-13: THE HANDOFF PORTS LEAK, and the third one is the last one

**FIXED LATER THE SAME DAY, and the hypothesis below is WRONG.** It is not
TIME_WAIT and `allow_reuse_address` has nothing to do with it: the ports are
genuinely LISTENING, because a module re-import orphans the socket. The
diagnosis is kept here rather than deleted, because how it was wrong is the
useful part - it was reasoned from the code rather than measured, and one
`netstat -ano` (three LISTENING rows, one PID) settled it in a second. See
*"the app never logged in"* below and
`.claude/rules/browser-login.md`.

Read off the product owner's own log:

```
00:21:26  Listening for a Canvas session handoff on 127.0.0.1:53127.
00:21:34  Accepted a Canvas session handoff for cbscanvas.instructure.com
00:21:46  Listening for a Canvas session handoff on 127.0.0.1:53128.   <- not 53127
00:22:18  Could not open a handoff port (53127, 53128, 53129 all in use).
00:22:30  Could not open a handoff port (53127, 53128, 53129 all in use).
```

So the listener walks up the list and then runs out, after which
`begin_browser_handoff` returns 0 and the card reports *"Could not open a
connection for the browser extension"* - **permanently, for the life of the
process**. That is a second, independent reason the product owner could not sign
in after the first successful handoff.

- **The likely mechanism, stated as a hypothesis rather than a measurement**:
  `_Server` sets `allow_reuse_address = False` (deliberately - the comment says
  "never inherit somebody else's socket"). After a handoff the accepted
  connection sits in **TIME_WAIT**, and on Windows a bind without `SO_REUSEADDR`
  is refused while any connection on that port is in that state. `start()`
  returns early when `_server is not None`, so reaching 53128 means `_server` was
  None while the port was still unavailable - i.e. a previous listener had been
  stopped and its port had not been released yet.
- **`SO_REUSEADDR` IS NOT THE FIX ON WINDOWS**, and this repo already records
  why: `release-and-packaging.md` documents `_find_free_port` being forbidden
  from setting it, because on Windows it means *"bind even if another process is
  LISTENING"* - it was measured handing out occupied ports. Setting it here would
  let anything on the machine steal the handoff port, which is precisely the
  threat model this listener is built around.
- **Directions worth measuring, none tried**: keep ONE listener for the life of
  the process and arm/disarm it in `_state` rather than binding and unbinding
  (which is what `start()`'s idempotent branch already does when `_server` is
  not None - the bug is the paths that set it back to None); or drain and close
  accepted connections explicitly so nothing lingers; or accept the walk but
  report the exhaustion to the user instead of a generic failure.
- **Reproduce it first**: press the extension card, complete a handoff, press it
  again, and watch which port each `start()` reports. It took about four cycles
  in the field.

## 2026-09-13: "the state of the canvas downloader status is pretty fucked and doesnt match the steps"

FIXED, and the fix was to stop asking a question that has no answer.

Reported alongside two others in the same message: after signing in
successfully the extension said *"Canvas Downloader is not running"*, and the
screen the student landed on was *"Nearly there"* plus *"Running but not asking
for a sign in yet"* - a three-step guide towards something that had already
happened.

**It was not a bug in the status line. The status line was right.**
`core/handoff.py` closes the socket as soon as the app consumes the handoff, so
`/ping` genuinely stops answering a second or two after a SUCCESSFUL sign-in,
and "not running" is the only honest reading of silence. The extension was
asking a question that stops having an answer at the exact moment it matters.

The product owner's own instruction settled the shape: *"if we cant properly
tell if the app is actually running after the sign-in, then the extension
should be designed around that - the text after click on button in the
extension and successful receive in the app should be a success message that
the app has been signed in and then mb a countdown from 5 or something to make
the transition to the 'step 0' state smooth."*

- The extension now REMEMBERS the sign-in it performed, in
  `chrome.storage.session`, instead of interrogating the app about it.
- The finished screen says "You are signed in", counts down from 5, and lands
  on a resting screen with no steps, no button and no guide: the logo, a green
  tick, and *"Canvas Downloader is signed in"* (plus "and running" only when a
  ping actually answered).
- One link leaves it: *"Something not right? Go through the steps again"*,
  which FORGETS the memory rather than just re-rendering.
- A live request for a sign-in always beats the memory, so a stale one can
  never stand between a student and the screen they need.
- The popup no longer closes itself 2.2 s after a sign-in. Since the app has no
  way to send a confirmation, that screen is the only one there is.

Mechanism, the wrong fixes and the measurements are in
`.claude/rules/browser-login.md`. Section 8 of `tests/test_handoff.py` covers
it, including `test_the_LISTENER_REALLY_DOES_STOP_after_a_handoff`, which pins
the premise against the real server so a lifecycle change fails in the same
commit.

**Also from the same message and now fixed**: the handoff port leak (see the
next entry). **Still open**:
the auth screen's own layout, which is waiting on the reference the product
owner said he would supply.

## 2026-09-13: "the app never logged in" - while the extension, the terminal and the checker all said it had

FIXED. Reported with the terminal output and a screenshot of the amber
*"Canvas sign-in did not finish"* card:

> "even though the extension did the countdown after all the steps were green,
> i was in the canvas site and i had clicked the button in the app, the app
> never logged in.."

and, separately, that `python scripts/check_handoff.py` reported every check
passing at the same moment.

**One cause.** Streamlit's watcher unloads every watched module on any file
change, so `core.handoff` was re-imported and the socket it had opened stayed
LISTENING with nothing holding a reference. `netstat` showed one `python
dev.py` holding **53127, 53128 and 53129 at once**. The extension takes the
first port that answers - the oldest ORPHAN - which accepted the handoff and
logged it into state the live module cannot read.

So three separate "it worked" signals were all true and all about the wrong
listener. The trigger was a mutation pass writing to `core/handoff.py`,
`ui/auth.py` and `app.py` 76 times while the dev host was running.

The listener now lives in a synthetic module a watcher cannot unload, so a
re-import ADOPTS it. `scripts/check_handoff.py` now probes every port and fails
when more than one answers. Mechanism, measurements and the wrong fixes are in
`.claude/rules/browser-login.md`; section 9 of `tests/test_handoff.py` covers
it.

**The third symptom in the same message is the same bug.** "if it first time
says canvas sign in did not finish, then when i click the browser login option,
it wont give me the card thats supposed to show that its searching" - that is
`begin_browser_handoff` getting 0 back from `start()` because all three ports
were held, so `handoff_waiting` was never set and the waiting card never
rendered. It should stop happening now that ports cannot leak; if it is ever
seen again with only ONE listener running, it is a separate defect and needs
its own repro.

## 2026-09-13: the extension said success, the app said the sign-in did not finish

FIXED, and it was three faults stacked rather than one.

Reported with the terminal log and the observation that pressing the button a
SECOND time signed him in - after the extension had already sent the session.

**The log's most useful line is the one that is missing.** There is no second
`Listening for a Canvas session handoff` after 02:03:33, so the listener was
armed the whole time and the credential was sitting there uncollected.

1. **Arrival switched off the collector.** The waiting card's poll is the only
   thing that asks for the Streamlit run which collects the handoff, and it was
   rendered only while `handoff.waiting()` - which goes False the instant the
   handoff lands. A one-second tick usually wins that race; a backgrounded tab
   on a slow laptop does not, and the app had just opened a Canvas tab in front
   of itself. **The slow laptop found this. It is the right machine to test on.**
2. **A stale failure card outranked an attempt in flight**, because starting a
   handoff cleared neither route's failure flag.
3. **Five specific causes were computed and thrown away** - the failure was used
   only as a truthiness test - so every cause rendered one generic sentence.
   That is why a good credential produced *"Canvas sign-in did not finish"*.

Also fixed: pressing the button again used to DISCARD an uncollected handoff,
which is the worst possible answer for the student who could not see that it
had worked.

**The cards now follow the flow**, and the two routes are kept strictly apart -
Path B (the Chrome extension) may talk about the Chrome button, Path A (the
app's own Canvas window, no extension needed) never does. Friction removed: the
waiting card says where Chrome hides a newly-installed button, and says
outright that if it is not there at all the extension is not installed and Path
A needs none.

**The other three things in the same report, all explained:**

- *The extension icon did not show it had recognised anything.* The badge was
  only repainted by a once-a-minute alarm. It now repaints whenever the popup
  asks for status, from the same answer, at no extra cost.
- *"Refused a Canvas session handoff from a non-extension origin" twice while
  doing nothing.* That was Claude's test suite: a checker test pointed the real
  `check_handoff.py` at port 53127 - his running dev host - and deliberately
  POSTs a web-origin request to confirm it is refused. The app behaved
  perfectly. Fixed by `_require_sole_ownership()`, which makes those tests skip
  when anything else holds the ports.
- *"Adopting a credential from a reloaded module", and is that constant?* No,
  and the assumption behind the question is worth correcting: **a Streamlit
  rerun is not a module reload.** A rerun re-executes the script with modules
  already imported and is harmless. A reload only happens when the file watcher
  sees a file CHANGE on disk - which it did, because Claude was editing source
  while his dev host ran. The shipped app passes
  `--server.fileWatcherType=none`, so it cannot happen there.
