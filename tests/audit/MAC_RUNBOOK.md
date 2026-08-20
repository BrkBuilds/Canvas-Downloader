# macOS live audit — the runbook

This is the **macOS-only** companion to `RUNBOOK.md`. Everything in that file
still applies; this one covers what a Windows machine structurally cannot
reach, ordered by *(historical bug density × can-only-be-tested-here)*.

Read `RUNBOOK.md` "Ground rules" and "The one idea that makes this suite work"
first. The rule that governs every finding is unchanged:

> **A finding is a disagreement between two oracles, and every finding names
> the pair.** O1 UI · O2 debug log · O3 disk · O4 sync manifest · O5 Canvas API.

---

## Why this file exists

A 2026-08-10 sweep drove **every** macOS branch in the codebase from Windows by
answering `sys.platform`/`platform.system()` as darwin and calling the real
functions (`tests/test_macos_platform_branches.py`, 61 assertions, 16/16
mutations caught). That closed the *logic* half. What it explicitly could not
prove is everything below: it checked the bytes we write, never whether macOS
accepts them.

**So do not re-verify logic here.** If a question can be answered by a unit
test, it already has been. This machine's time is worth spending only on
things that need a real window server, a real Keychain, real Office, a real
WKWebView and a real code signature.

---

## THE TRAP THAT COSTS HOURS: window-server access

The audit needs a process that can reach the **window server**. Without it:

- `osascript` cannot drive Word/Excel/PowerPoint (every Office conversion fails),
- Playwright cannot open a headed browser,
- TCC prompts cannot appear (so grants can never be given),
- `pywebview` cannot create a window (the packaged app will not start).

Each fails differently and none of them says "you have no window server".

**Test the capability, never a proxy:**

```bash
screencapture -x /tmp/probe.png && ls -la /tmp/probe.png
osascript -e 'tell application "System Events" to return name of first process'
open -a TextEdit && sleep 3 && osascript -e 'tell application "System Events" to return exists application process "TextEdit"'
```

A real PNG, a process name, and `true` mean you are fine.

**Do NOT gate on `launchctl managername == "Aqua"`.** That was this file's
original advice and it was wrong. Measured on a Scaleway Apple-silicon Mac
(2026-08-10) it reports **`Background`** from SSH *and from Terminal.app on the
desktop*, while all three probes above pass. `managername` names how the
session was established - auto-login, NoMachine and a physical login all label
differently - and says nothing about what a process can reach. Two hours were
lost to that proxy, on a machine that was entirely healthy.

**When the probes genuinely fail**, the cause on a cloud Mac is almost always
that no console session exists:

```bash
stat -f%Su /dev/console        # must be your user, not root
```

`root` means the Mac is sitting at a login window with no framebuffer - screen
sharing shows black and GUI automation is impossible. Scaleway's image sets
`autoLoginUser` but never writes `/etc/kcpassword`, so auto-login never
completes. Write it and reboot:

```bash
sudo python3 -c 'k=[0x7D,0x89,0x52,0x23,0xD2,0xBC,0xDE,0xC7];p=b"<password>";n=(12-len(p)%12)%12 or 12;b=p+bytes(n);open("/etc/kcpassword","wb").write(bytes(c^k[i%8] for i,c in enumerate(b)))'
sudo chmod 600 /etc/kcpassword
sudo reboot
```

`scripts/mac_audit_doctor.py` probes all of this directly and reports the
launchd domain as INFO only.

### THE OTHER HALF OF THE SAME TRAP: the Keychain *is* session-scoped

Everything above is true **of the window server** and does not carry over to the
**Keychain**, which is the one macOS service scoped to the launchd *security*
session rather than to the framebuffer. Measured 2026-08-10, in ONE shell on a
Scaleway Apple-silicon Mac:

```
screencapture                     -> a real 4.4 MB PNG
System Events                     -> answers
osascript / GUI automation        -> works
keyring.set_password(a NEW item)  -> errSecInteractionNotAllowed (-25308)
```

So a tmux server started over SSH gives you a `Background` session that can
drive the entire GUI and **cannot touch the Keychain at all** - not even to
create an item of its own, where no ACL and no password are involved. The app
under test is a child of that shell, so *every* Keychain observation becomes
false: token save "fails", auto-login "does not restore", and the 90 s watchdog
looks like it is being hit. **None of that is the product.**

Two independent failures land on the same symptom, and both bit in one session:

1. **The session** (above). Fix it at the root: work in a shell that was born
   inside the graphical session. Since 2026-08-20 the standing workflow does
   that by construction - **VS Code running on the Mac's own desktop, reached
   over NoMachine** - because Launch Services starts it in Aqua and its
   integrated terminal inherits that. The older answer, a tmux server started
   from a Terminal on the desktop and attached from SSH, achieves the same
   thing and is still valid as a fallback. If you are already mid-session,
   `scripts/mac_aqua.py` hands one command to Terminal.app (which Launch
   Services also starts in Aqua) and every child inherits it, including a
   long-lived Streamlit:

   ```bash
   python3 scripts/mac_aqua.py check                       # session + Keychain, one line each
   python3 scripts/mac_aqua.py run "python -m tests.audit app start"
   ```

   `tests/audit/harness/appctl.py` passes `start_new_session=True` on POSIX so
   the app survives that Terminal window closing.

2. **The item's ACL.** A keychain item records which binaries may read it
   without authorisation, and that list is set by whoever *creates* it. Seeded
   by `/usr/bin/security`, the ACL names `security` - which reads it back
   silently, so the seeding looks successful - while every real consumer (the
   app, and the harness's O5 client, both **python**) is asked to authorise
   itself, and authorising an ACL change requires the **login keychain's own
   password**. On a cloud image that is often the image's original password and
   nobody has it. `-A` does not help; it was set.

**The doctor said READY in exactly that state**, because `check_credentials`
probed with `security` - a different client from every consumer, which is the
same mistake `CLAUDE.md` records as verifying a copy instead of the real thing.
It now (a) round-trips a **brand-new item of its own** to test the session as a
capability, and (b) re-reads the token with **python**, both `BLOCK`, both
bounded by a daemon-thread watchdog so a password prompt cannot hang the
preflight. `mac_audit_bootstrap.sh` seeds via python keyring and verifies the
read-back.

Highest fidelity of all, and what a real user does: delete the item and **log in
once through the app UI**, letting the app create its own. That is also the
genuine M5 save test - verify the item's `cdat` is the moment you logged in, then
that python reads it with no prompt.

---

## Preflight

```bash
cd ~/Canvas_Downloader && source .venv/bin/activate
python scripts/mac_audit_doctor.py         # must print READY
python scripts/mac_smoke.py --with-hfs     # every non-visual macOS check, ~2 min
python -m tests.audit run new --label macos-15-v2.0.2
python -m tests.audit app start
python -m tests.audit browser open
python -m tests.audit canvas courses
python -m tests.audit flow download smoke --courses 43667   # ~seconds
```

If the smoke row does not complete, stop and fix the harness before spending
Mac time on the product.

### `scripts/mac_smoke.py` does the non-visual half for you

Run it **first** and again after every fix. It covers, automatically, what the
phases below otherwise ask you to do by hand:

| It checks | Phase it front-runs |
|---|---|
| `make_long_path` no-op, >600-char paths, the 255-BYTE component limit | M4 |
| APFS normalisation-preserving; `_path_key` across NFC/NFD | M4 |
| **A real HFS+ volume** via `hdiutil` — the one place NFD is not a no-op (`--with-hfs`) | M4 |
| `.webloc` written, parsed, marker-recognised, accepted by `open -R`; Windows `.url` adopted; the URL compiler sparing ours | M2 |
| `osascript` reachable; a quote+CR filename surviving the literal; `applescript_string` compiling | M1 |
| Office installed, Automation working, **nothing left running** (`--with-office`) | M1 |
| Keychain round trip, the 90 s watchdog, **no token file on disk** | M5 |
| Which link of the notification chain wins; the osascript fallback compiling | M5 |
| Bundled ffmpeg on arm64; `ctranslate2` importing in a clean process | M2 |
| Hardware probe: `is_mac`, no CUDA claimed, CPU recommended | M2 |
| Bundle: Info.plist, signature, **apple-events entitlement**, worker binary, **WebKit lookbehind patch**, boot splash, no tornado opener (`--bundle "dist/Canvas Downloader.app"`) | M3 |
| No stray Canvas/ffmpeg processes; no duplicate GUI launches | M3 |

What it leaves out is anything needing eyes — **and you may or may not have
eyes. Check first:**

```bash
python3 scripts/mac_eyes.py eyesight     # BLIND, or window content capturable?
```

Taking a screenshot needs a **Screen Recording** grant, and without one macOS
**does not fail the capture** — it silently omits every other application's
window and hands back a picture of the desktop. Only the window-targeted form
(`screencapture -l <winid>`) errors, with *"could not create image from
window"*. Measured on a Scaleway Mac 2026-08-10: one display, the window server
listing **12–31 windows** including the packaged app's own 1920x970, the
operator looking straight at them, and every capture blank.

**And the grant is per-RESPONSIBLE-process, which is what makes it confusing on
a remote box.** TCC attributes the capture to the session's responsible
process — for an SSH/tmux shell that is `sshd` or the CLI binary, *not*
Terminal.app. Measured minutes apart, same machine, same user, same display:

| context | verdict |
|---|---|
| the SSH tmux shell | **BLIND** |
| `scripts/mac_aqua.py run ...` (children of Terminal.app) | window content is capturable |

So granting Terminal.app does nothing for the SSH shell. **Take visual shots
through the bridge**, or grant Screen Recording to the real responsible process.

**In the standing workflow that responsible process is Visual Studio Code**,
because the agent runs in the terminal of a VS Code launched from the Mac's own
Dock. So the Screen Recording grant goes to **VS Code, not Terminal** - Part 3
of `MAC_AUDIT_GUIDE.md` puts it in the setup checklist for exactly this reason.
Verify it rather than assume it: `python3 scripts/mac_eyes.py eyesight`, and
treat a WARN from the doctor's "screenshots can render window content" check as
"hand every visual question to the operator", never as evidence about the app.

**The failure points the wrong way.** A blank capture is indistinguishable from
a blank app, and "the UI is blank in WKWebView" is precisely the failure phase
M3 exists to catch — so an agent trusting the screenshot files a CRITICAL
against a build rendering perfectly. This nearly happened: the packaged app's
login screen captured as an empty desktop and was only cleared by the operator
sending a screenshot from their own viewer.

A first diagnosis blamed NoMachine's display driver and was **wrong**. The
correction came from running the same probe in both contexts — do that before
believing any conclusion about the environment. `mac_audit_doctor.py` reports it
as a WARN.

With eyesight confirmed, `scripts/mac_eyes.py` reads the real window server:

```bash
python scripts/mac_eyes.py shot --window "Canvas Downloader"
python scripts/mac_eyes.py watch --seconds 20   # transients: banner, splash
python scripts/mac_eyes.py dialogs              # anything awaiting a human?
python scripts/mac_eyes.py dock                 # tiles whose target is gone
```

So "is the banner visible", "does the packaged app render correctly in
WKWebView", "is there a stale Dock tile" are all yours to answer. The genuine
human-only residue is small: pressing the button on a **TCC consent prompt**
(macOS refuses synthetic clicks there by design) and confirming a
**double-clicked `.webloc` actually opens** in a browser.

---

## Phase M1 — Office converters *(highest risk; do this first)*

The macOS branch of all three converters deleted the user's only copy of a
`.doc`/`.xls`/`.ppt` on an unverified PDF for a full round after the Windows
gate shipped. The logic is now tested; **the osascript/TCC/staging machinery
around it is not.**

1. **The first-run permission batch.** `engine.applescript_bridge.first_run_permission_setup`
   launches every enabled Office app hidden and fires the TCC-triggering events
   so all the Automation prompts arrive in one predictable moment. Watch it
   happen. Grant everything.
   - **Do NOT report the batch re-firing on later runs.** `_permission_record_path()`
     lives in `get_config_dir()`, which the audit isolates per run — so the app
     legitimately believes it is first-run every time. On a real user's machine
     the record persists. Harness interaction, not a defect.
2. **Convert for real**: a legacy `.doc`, `.xls` and `.ppt` (course 43660 has
   legacy Office files). Verify the PDF is real and the source is gone.
3. **Force the failure the gate exists for.** Two ways, both cheap:
   - password-protect a `.doc` and convert it → the original must SURVIVE and
     the log must say why;
   - revoke Automation for Word mid-run (System Settings → Privacy & Security →
     Automation) → the phase must abort once with one actionable message, not
     emit one generic error per file (`_abort_applescript_phase`).
4. **A filename that would break the AppleScript literal.** macOS permits every
   byte but `/` and NUL:
   ```bash
   touch "$(printf 'Lec\rture.doc')"      # carriage return
   touch 'Say "hi".doc'                   # quote
   ```
   Both must convert normally — `_as_posix` neutralises them.
5. **Office must not leak.** After the phase: `pgrep -fl "Microsoft (Word|Excel|PowerPoint)"`
   must be empty once `quit_idle_office_apps` has run. A leaked `EXCEL.EXE` is
   an *open* finding on Windows; check whether the Mac has the same shape.
6. **Dock recents tiles.** `purge_stale_self_dock_tiles` exists because a
   conversion left a Dock tile pointing at a file the app had deleted. Look at
   the Dock after the phase.
7. **Long paths — SETTLED 2026-08-20, see the section below.** The premise
   here was wrong twice over: `office_safe_path` is a documented **no-op off
   Windows**, and the component limit is **255 UTF-16 code units**, not bytes
   (measured — 510 bytes of `æ` is legal, 512 bytes of emoji is not). What
   actually handles length on macOS is `office_container_stage`, which stages
   every conversion under a short `src_<hex>` name. A 900-char path converts.
8. **WHO THE APP BELONGS TO — the one thing on this list that has never run on
   a Mac** (added 2026-08-13). The quit gate decides whether to send
   `quit saving no` to an app that may hold a student's unsaved essay, and its
   three known failure modes were fixed against a *Windows simulation*
   (`sys.platform` patched to darwin, `pgrep` and `_warmup_apps` modelled).
   That proves the DECISION path. It does not prove the other half of the
   chain — that a conversion phase leaves the documents undescribable, which is
   the 2026-08-12 measurement and is what makes a wrong decision destructive.

   Three checks, in this order. Each needs `pgrep -x "Microsoft Word"` before
   and after, and the `[OfficeQuit]` lines from `debug_log.txt`.

   a. **FIRST RUN on this machine.** Delete the permission record
      (`rm "$(python -c 'from shared.helpers import get_config_dir; print(get_config_dir())')"/office_permissions.json`)
      and `pkill` all three apps. Run a download that converts. `first_run_permission_setup`
      launches all three for the TCC batch — the gate must still quit them
      afterwards. **Before the fix this left all three in the dock with Recents
      full of our `src_*` files**, because the observation was taken after our
      own launch.

   b. **TWO RUNS IN ONE SESSION, the user opens Word in between.** This is the
      data-loss path and the reason this step exists.

          run 1  nothing open -> download+convert -> all three quit
          then   open Word, type something, DO NOT SAVE, leave it open
          run 2  download+convert a second course, WITHOUT restarting the app

      **Word must survive run 2 with its document intact**, and the log must
      read `left alone (we did not launch it)`. Before the fix the observation
      was per PROCESS, so run 2 answered with run 1's facts, called Word ours,
      and — because run 2's conversion phase had just made the documents
      undescribable — quit it `saving no`.

   c. **CANCEL before anything primes.** Start a download with Word open and
      cancel immediately. The teardown fires on the cancelled screens too, and
      an app we never observed must read `left alone (we never drove it this
      run)`.

   `scripts/verify_office_end_to_end.py` DRIVES ALL THREE as of 2026-08-13,
   and the important half of that change is not the new states: it now runs the
   app's real run-start sequence (`reset_office_priming` →
   `first_run_permission_setup` → per-course `prime_office_automation`)
   instead of calling the converters directly. Priming is what launches the
   apps, so who-launched-what was never decided the way a real run decides it
   — which is exactly why every harness in this repo passed while D11 was
   live.

       python scripts/verify_office_end_to_end.py --state cold --forget-permissions   # (a)
       python scripts/verify_office_end_to_end.py --state two-runs                    # (b)
       python scripts/verify_office_end_to_end.py --state cancel                      # (c)

   Each prints JSON ending in `VERDICT` and exits non-zero on a problem. They
   assert the `[OfficeQuit]` **reason**, not merely the outcome — a stale
   "ours" that happened not to quit Word would pass every outcome check, so
   (b) requires `left alone (we did not launch it)` and (c) requires `left
   alone (we never drove it this run)`. Both strings are pinned against the
   bridge by `tests/test_mac_audit_tooling.py`, so a reword fails on Windows
   rather than here.

   `pkill`ing between runs is NOT a substitute for (b): the bug is about state
   inside one process, which is why `--state two-runs` keeps both runs in one
   interpreter. (a) deletes the answered-prompts record, so macOS re-asks and
   someone must be at the screen to click Allow.

## Phase M2 — Panopto *(entirely new since the last Mac audit)*

Nothing in this subsystem has ever run on macOS.

1. **Discovery** — LTI launches, `panopto_base_from_url`, the folder walk.
2. **`.webloc` shortcuts.** The unit tests prove we write a valid two-key plist.
   **Only this machine can answer whether Finder opens one.** Double-click it.
   Then check the Canvas ExternalTool collision case: a lecture that is also a
   module item must produce `<title> (Panopto).webloc` beside the Canvas link,
   not overwrite it.
3. **`converters/url.py` must spare our shortcuts** while compiling foreign
   ones. On macOS it deletes `.webloc` and *keeps* any `.url` from a
   Windows-synced folder — copy one in and prove it survives.
4. **mp3 and mp4** through the bundled ffmpeg on arm64. Verify as
   `RUNBOOK.md` "Do NOT report: `ffmpeg -f null`" describes — classify decode
   errors vs muxer noise, then check both streams, duration, `+faststart`, and
   that no `.part` remains.
5. **Transcription on Apple silicon** — the riskiest single item here.
   - There is no CUDA, so the CPU path is the only path; `panopto/hardware.py`
     must report that calmly rather than raising.
   - `ctranslate2` + `onnxruntime` are native arm64 wheels; the app already
     carries an OpenMP clash that **segfaults** rather than erroring, which is
     why `panopto/transcribe_worker.py` runs out of process. Confirm the worker
     is used and that a crash in it does not take the app down.
   - **Cancel mid-transcription.** The `.part` sweep now lives in a `finally`
     (a UI cancel is a `BaseException`). Verify no `<name>.txt.part` /
     `.srt.part` survive, and that the worker is reaped.
6. **Model download** into the config dir, and the "Manage installed models"
   dialog when one is installed.

## Phase M3 — The packaged `.app` *(the class the harness cannot reach)*

**The audit harness drives detached Chrome over CDP. The shipped app renders in
WKWebView.** Everything CSS/JS is therefore *unverified* until you run the
bundle. Nearly every macOS bug in `CLAUDE.md` is packaging-only.

```bash
pip install pyinstaller      # NOT in requirements.txt and NOT installed by
                             # mac_audit_bootstrap.sh - measured 2026-08-11,
                             # where M3 began with "pyinstaller: command not
                             # found". ~40 s; do it before you need it.
pyinstaller --clean Canvas_Downloader_macOS.spec
codesign --force --deep -s - --entitlements entitlements.mac.plist "dist/Canvas Downloader.app"
open "dist/Canvas Downloader.app"
```

Check, in order:

1. **The window is never empty.** `start.py` and the patched `index.html` paint
   the same splash; a difference between them *is* the flicker. Watch the first
   two seconds.
2. **WKWebView-only rendering.** `scripts/patch_streamlit_webkit.py` strips a
   lookbehind regex WKWebView cannot parse. If the UI is blank or the console
   shows a regex error, that patch did not apply. Then walk every screen and
   compare against the Chrome screenshots from phase M4 — this is the only
   opportunity to catch a WebKit-specific layout break.
3. **argv drop.** A `.app` loses subprocess argv, which is why the transcription
   worker is routed by the `CANVAS_DL_TRANSCRIBE_WORKER` env var. Run one
   transcription **from the bundle**.
4. **Phantom instance.** The multiprocessing `resource_tracker` used to re-exec
   the app binary. Launch, sync, quit — exactly one Dock icon throughout, and
   `~/Library/Application Support/CanvasDownloader/duplicate_launches.log`
   should stay empty.
5. **Keychain on a REBUILD.** A clean install never prompts; a rebuild with a
   *new ad-hoc signature* reading the previous build's item triggers the
   one-time "enter login keychain password" prompt. Build twice and confirm the
   90 s watchdog does not abandon it.
6. **SSL/certifi** — the frozen app has its own bundle path. Any Canvas call
   working proves it; a `ValueError` that is really a cert error is the
   documented trap.
7. **TCC identity.** The bundle is a different binary from `python`, so
   Automation prompts re-fire for the .app even though Terminal was granted.
8. **Quit → orphan reaping.** After quitting, no `ffmpeg`, no worker, no
   WebView2-equivalent left: `pgrep -fl -i "canvas|ffmpeg|transcribe"`.

## Phase M4 — Download + sync matrices

Run the standard matrices (`RUNBOOK.md`) so macOS gets the same coverage
Windows has. Two macOS-specific additions:

1. **HFS+ / NFD — the one place `_path_key`'s Unicode normalisation is not a
   no-op.** APFS is normalisation-preserving so a modern Mac hides this
   entirely; an external drive does not. Make one:
   ```bash
   hdiutil create -size 400m -fs "HFS+" -volname NFDTest ~/nfd.dmg
   hdiutil attach ~/nfd.dmg           # mounts at /Volumes/NFDTest
   ```
   Sync a course with Danish characters into it. `å` decomposes; `ø` and `æ`
   do not — so a partial symptom is the *expected* shape, and a file dropping
   out of the tracked set (or inflating the "untracked files" count) is the
   defect. Detach and `rm ~/nfd.dmg` afterwards.
2. **Case-only rename** on the case-insensitive boot volume: rename
   `Notes.pdf` → `notes.pdf` between syncs; it must stay tracked.

## Phase M5 — The rest of the platform surface

- **Notifications.** The chain is UNUserNotifications → NSUserNotification →
  pync → osascript. Confirm a banner actually appears after a sync. `pync` is
  documented as unreliable on arm64 Sequoia, so on macOS 15 the interesting
  question is which link in the chain wins. To force the last one, temporarily
  make the first three fail — the osascript literal was fixed 2026-08-10 and
  has never run on a Mac.
- **Folder picker** (`native_folder_picker`, osascript `choose folder`),
  including a folder whose name contains a quote.
- **Keychain** save → restart → auto-login → logout → item gone.
- **Reveal in Finder** and **Open Folder** from the completion screen.
- **App Data consent** is transient per process by design — re-armed every run.
  Do not report it as a leak.

---

## Recording

Same as `RUNBOOK.md`:

```bash
python -m tests.audit finding add "<one-line title>" \
    --severity <sev> --category <cat> --oracles O1,O4 \
    --detail "$(cat detail.txt)" --evidence '{"json": "only"}' --scenario mac_<id>
python -m tests.audit report build
```

`title` is POSITIONAL and required. `--oracles` is how the "name the pair" rule
is recorded — use it on every finding.

Prefix every macOS-only finding's scenario with `mac_` so the register can be
sliced later. **Name the oracle pair.** If something can only be observed by
eye (Finder, the Dock, a banner), say so explicitly and attach a screenshot —
that is legitimate evidence here in a way it is not on Windows.

## Do NOT report

- The first-run Automation batch re-firing every run (isolated config dir).
- App Data consent being re-requested per process (documented, by design).
- `ffmpeg -f null` muxer warnings on Panopto mp4 (see `RUNBOOK.md`).
- `pync` doing nothing on arm64 — it is a documented fallback, not the primary.
- Anything already listed in `RUNBOOK.md`'s "Traps this harness already knows
  about" and the checker-defect sections.

## STILL UNPROVEN after the macOS 15 run (2026-08-10)

Run `20260810_151922_macos-15-v2.0.2` covered M1-M4 and part of M5, fixed five
product defects and recorded four more. What it did **not** reach, in the order
worth picking up — each with what specifically blocks it, so no one re-derives
that:

1. ~~**The mp4 output.**~~ **DONE 2026-08-10** — all 36 recordings, both streams
   and `moov` before `mdat` on every one, and the DTS trap characterised: the
   warning comes from a *re-mux*, prefixed `[null @ …]`, with the app's own log
   showing **0** such lines. See the M2 PASS finding. Two things to reuse: the
   bundle ships **no ffprobe**, so verify with `ffmpeg -i` plus an atom walker;
   and the recordings are 20–140 MB, not ~100 MB average, so the full set is
   **2.0 GB and finishes before you can cancel it** — budget for all of them.
2. ~~**Keychain on a REBUILD.**~~ **DONE 2026-08-11 on macOS 26.6**, and the
   reason it was blocked is WRONG on this image. This entry used to say the
   one-time prompt asks for the login keychain's own password, "which is unknown
   on a cloud image (measured — the Scaleway password does not open it)". On the
   Tahoe install **the Scaleway password DOES open the login keychain** (operator
   confirmed, twice). Try it before assuming this is unreachable.
   - The prompt fires for a genuinely different reason than "a rebuild", and the
     stronger version is worth knowing: the **.app is a different binary from
     `python`**, so it hits the ACL of an item the harness's python keyring
     created and macOS asks *"Canvas Downloader wants to use your confidential
     information stored in 'CanvasDownloader' in your keychain"*. You do not need
     to build twice to see it — build once and launch the bundle.
   - Answered Allow, then Always Allow on a second prompt: the app **restored the
     session** and came up logged in. The 90 s watchdog did not abandon it while
     the prompt was open.
   - Note the bundle's config dir is `~/Library/Application Support/
     CanvasDownloader`, not the repo root, so a fresh bundle shows the LOGIN page
     until you seed `canvas_downloader_settings.json` there. That is not a
     Keychain failure — check it before chasing one.
3. ~~**The folder picker's RETURN path**~~ **DONE 2026-08-10**, and ~~**the MODAL
   itself**~~ **DONE 2026-08-11 on Tahoe** (operator clicked Choose; macOS
   refuses synthetic clicks here). Probe: `Kurt's "Økonomi" mappe — æøå`, i.e.
   every character class that has ever broken an AppleScript string literal or a
   path key, driven through the REAL `native_folder_picker`. All of it holds —
   the name comes back whole (the `"` is the one that matters: unescaped, it
   terminates the literal), and **the panel opens at the PARENT**, which is what
   `picker_start_for_existing` is for.
   - The return carries a **trailing slash** (AppleScript's `POSIX path of`, so
     a *picked* folder differs in spelling from a typed one — Windows and
     tkinter both return bare paths). `save_pair`, `pair_key` and `_path_key`
     all collapse it, so one link cannot become two pairs.
   - **CORRECTED 2026-08-11: `_path_key` does NOT collapse the `/private` form**
     — this line used to claim it did. Measured on Tahoe:
     `_path_key("/tmp/x") != _path_key("/private/tmp/x")`. It has never
     mattered and needs no fix: `/tmp` is a **symlink** to `/private/tmp`, which
     is why a probe *there* sees the resolved form at all, and course folders do
     not live in `/tmp` — `~/Downloads` is not a symlink, so the picker returns
     the same spelling the app stores and both sides of every later comparison
     agree. **Do not "fix" this by resolving symlinks inside `_path_key`**: it is
     the key three comparison sites share, and making it hit the filesystem
     would give it a failure mode (and a cost) it does not have today.
   - **The correction to make here: Accessibility is not simply absent.**
     *Reading* works (a frontmost-process query answers), so the old `-1728`
     note is wrong. **Synthesising input is a separate gate** and it is denied:
     System Events answers *"osascript is not allowed to send keystrokes"*, with
     `kTCCServiceAccessibility` for `com.apple.Terminal` at `auth_value 0`.
     Cmd-Shift-G produced no sheet; type-ahead is what surfaced the real refusal.
     The modal was therefore dismissed by the **operator**, which took seconds —
     for a single modal, asking is cheaper than the permission dance.
   - **Still needs the grant: Reveal in Finder / Open Folder**, and reading a
     wedged app's window list.
   - **A trap that cost a cycle: check eyesight in the SAME context you capture
     from, not once per session.** The first screenshot of the open dialog showed
     an EMPTY DESKTOP because it was taken from the SSH shell, which has no
     Screen Recording — only `com.apple.Terminal` does. It silently omitted every
     window, including the Terminals. Re-shooting through the bridge showed the
     dialog immediately.
4. ~~**The macOS-15 FDA nudge.**~~ **DONE 2026-08-10**, all four surfaces. The
   note here used to say it needs Terminal removed from Full Disk Access; that
   was **wrong twice over** and cost a cycle each time, so read this instead:
   - Removing Terminal's grant is **not sufficient**. TCC's `access` table went
     to **zero** rows for `kTCCServiceSystemPolicyAllFiles` and a process spawned
     seconds later from Terminal still read the protected file — the capability
     is cached against the responsible process and survives both the revocation
     and a Terminal restart. Do not go down the `killall tccd` road; it does not
     clear it either.
   - It is also **not necessary**. The SSH session's responsible process
     (`/usr/libexec/sshd-keygen-wrapper`) carries an explicit *denied* FDA row,
     so **just start the app from the SSH shell instead of the Aqua bridge** and
     `has_full_disk_access()` is False for real, with nothing patched. The one
     cost is the Keychain (Aqua-scoped), so `restore_saved_session` lands on the
     login page — paste URL + token into the real form, which takes seconds and
     incidentally proves a keyring failure cannot block a login.
   - **THAT SSH RECIPE DOES NOT WORK ON macOS 26** (2026-08-11): on this Tahoe
     install `sshd-keygen-wrapper` **has** Full Disk Access, so the SSH shell is
     granted and the nudge never renders. Do not re-derive this.
     **Use whichever shell the agent is already in and MEASURE it** rather than
     assuming any particular one is denied — TCC attributes a grant to the
     *responsible process*, and an agent running under a VS Code extension host
     is its own responsible process, not Visual Studio Code. Here that shell
     reported `has_full_disk_access() == False` while holding Screen Recording
     and Automation, which is the whole state the recipe needs, with no SSH and
     no Keychain cost — so the app can be driven normally. One line settles it:
     `python -c "from engine.applescript_bridge import has_full_disk_access as f; print(f())"`.
   - Reaching the *card* needs one more step: the audit config ships
     `fda_nudge_dismissed: true`, so the slot renders the subtle re-spawn link.
     Click it.
5. ~~**The notification BANNER, visually.**~~ **CLOSED as unreachable from
   source, 2026-08-10, and do not spend time on it again.** A source run has no
   bundle identity, so macOS attributes the request to an app called **"Python"**
   — confirmed by opening System Settings → Notifications, which showed exactly
   that with *Allow notifications* off. So `granted=False` /
   `authorizationStatus=0` here says nothing about the product. 36 captures at
   0.25 s intervals of the banner corner were **byte-identical**: nothing is ever
   displayed, and firing repeatedly gets the process **Killed: 9**. Notifications
   are confirmed working in the frozen build (prior audit + operator). What the
   attempt DID find is a real code defect —
   `_show_macos_notification_un` returns True before the async completion handler
   sees the error, so a rejected request is reported as success and all three
   fallbacks are skipped; see its finding. Testing that properly needs the
   packaged app with a real *Don't Allow*, not a source run.
   - **STOP TESTING NOTIFICATIONS BY FIRING THEM. Operator instruction,
     2026-08-11, and it explains a pattern across two audits.** Every attempt to
     drive this path costs the OPERATOR, not the agent: a source run calls
     `request_macos_notification_permission()` at `app.py:57`, which raises the
     **"Python" Notifications** authorization prompt; the notification path
     **crashes a short-lived python process** (already recorded above as
     "Killed: 9"); the agent then retries; and each retry re-launches something
     that trips the **Keychain** prompt as well. In the macOS 15 session the
     operator had to answer that loop repeatedly — and had no password for the
     keychain dialog, so the runs were dead anyway. *"I think you need to
     actually rethink your strategy in testing this."*
   - **The rethink: READ THE SYSTEM'S RECORD, do not produce banners.** And when
     the record is unreadable, say so and stop — an unanswered question is
     cheaper than a prompt storm on a machine the operator is sitting at.
   - **What that costs is that this may be unanswerable here, and 2026-08-11
     showed exactly that.** With a genuinely clear screen (`mac_eyes dialogs`
     reported nothing waiting), one `osascript display notification` produced
     **no banner**: the full-screen before/after diff changed only a 7x151px
     text cursor at the bottom-left, nowhere near the banner corner. That is a
     clean measurement of "nothing displayed" — but NOT of *why*, and both ways
     of finding out are closed. Focus/Do Not Disturb state lives in
     `~/Library/DoNotDisturb/DB/ModeConfigurations.json`, which is TCC-protected
     (`Operation not permitted`) and reading it harder means another prompt; and
     **`log show` returns ZERO lines for any predicate in this context**, so the
     unified log cannot corroborate it either. Verify that control before
     trusting a log-based approach: `log show --last 60s | wc -l`.
   - **A "no banner" result needs a POSITIVE CONTROL and there isn't a free
     one.** Without something that definitely SHOULD display, "nothing appeared"
     and "Focus is on" are indistinguishable. Do not report the first when you
     have only measured the second.
6. ~~**A 250-char path component** fails to convert~~ **DIAGNOSED AND FIXED
   2026-08-10**, and it was worse than this note said: **any** filename past
   about **164 bytes** could not be converted at all. The limit is Word's
   ~255-character **TOTAL path**, and `office_container_stage` was spending 91 of
   that budget on the container prefix while preserving `src.name` — i.e. it
   shortened the directory, which was never the problem, and kept the name, which
   was. Now stages as `src.<ext>` / `out.<ext>`; a 240-byte name converts and the
   PDF lands under its real name. Three things to reuse:
   - **Every case needs a FRESH Word and its own positive control**, or it
     measures the previous case's wedge. Both earlier logs show the shape: control
     converts, case 1 times out (-1712), cases 2-8 all report `missing value
     doesn't understand the "save as" message`.
   - **The unstaged path is NOT a usable control.** Without the container macOS
     demands the per-folder App Data grant that staging exists to avoid, so even a
     short-named control fails there — and an intermediate draft of this analysis
     concluded "component, not total path" from exactly that unsound comparison.
     **Vary the depth INSIDE the container** instead: a 9-byte name at staged ~220
     converts while an 11-byte name at staged ~281 fails, which is what rules a
     component limit out.
   - `active document doesn't understand …` (Word opened it) and `missing value
     doesn't understand …` (Word did not) are **different** signals. The second is
     the wedge.
7. ~~**The sync matrix** (43 rows)~~ **DONE 2026-08-10**: 43/43 rows, 2 lanes,
   **0 failed**, 100% 2-way and 3-way-interacting coverage. Four things to reuse:
   - **Snapshot a MEDIUM course.** The already-downloaded Panopto course is 467
     files / 3.8 GB and 43 lane copies of it is ~160 GB. Course 46386
     (`Virksomhedens økonomiske styring (2)`) is 97 files / 92.5 MB across
     pdf+xlsx+pptx — a rich sync world for ~4 GB of lane copies.
   - **The matrix has NO converter axes**, so Office never runs and 2 lanes are
     far lighter than the 4-lane Office matrix that OOM-killed a 16 GB machine.
     Free+inactive fell 5.9 → 3.3 GB and recovered; it was never close.
   - **Lane apps restore their session from the KEYCHAIN**, so the matrix must be
     launched from the Aqua session (`mac_aqua.py run --detach`). With no token
     there, every lane app sits on `?mode=auth` and **every row fails with
     `btn_analyze_sync not clickable`** — which reads like a UI defect and is
     really "not logged in". Check one lane's screen before believing anything
     else. That symptom is what uncovered the failed-Keychain-save data loss.
   - **Never launch twice.** The first `--detach` prints nothing, which looks like
     failure; a second launch cannot bind the lane ports, exits, and runs its
     `finally` — which calls `appctl.stop()` and `close_browser()` on the SAME
     lane run dirs the live workers are using. Four rows failed for reasons that
     had nothing to do with the product. `matrix launch` now refuses when workers
     are already alive.
   - **The 6 CRITICAL findings it produced are fixture artifacts, not defects** —
     `readonly_target` was asserting Windows rename semantics. See the register
     entry `fp:6a83c06e72be`, whose notes now cover both times this fixture has
     misfired.

Traps this run paid for, worth knowing before you spend the same time:

- `mac_eyes eyesight` must be checked before believing any screenshot.
- Word **wedges** after a hostile document — so any Office test needs a positive
  control per case and a fresh Word between them, or every later result is
  vacuous.
- **Never pass prose to `finding add --detail` inside double quotes.** The shell
  ran the backticks and brackets in one write-up as command substitution and
  three fragments were silently deleted from the stored finding — including the
  `[null @ …]` prefix that was the whole point of the entry. Write the detail to
  a file and pass `--detail "$(cat file)"`, which does not re-interpret the
  content. Same family as the heredoc-mangles-backslashes note in CLAUDE.md.
- **A close-by-name AppleScript is not enough to clean up, and neither is a
  forgotten dialog.** Two cheap lessons: `mac_aqua.py` must close its Terminal
  window **by window id** (`saving no`) or windows accumulate by the dozen; and a
  Streamlit dialog left open makes the *next* `ui click` fail with a
  pointer-events timeout naming an unrelated element — use `ui press Escape`.
- **Counting duplicates by filename is a false-positive machine here.** These
  Canvas lecture titles literally contain `(1)`/`(2)`, so a glob for `*([0-9])*`
  reported **136** conflict copies where there were **0**. A real
  `_handle_conflict` copy is a stem *ending* in ` (N)` **whose un-suffixed
  sibling also exists** — check both halves.
- **There are THREE separate macOS permissions in play and they are easy to
  conflate.** Granting one does not grant the others, and each fails differently:
  | want to | needs | failure looks like |
  |---|---|---|
  | read process names / window lists | Accessibility | `-1728`, or an empty list |
  | send keystrokes / clicks | Accessibility (input synthesis) | *"osascript is not allowed to send keystrokes"* |
  | drive a NAMED app (Finder, Word) | **Automation**, per (source app → target app) pair | a **consent prompt that BLOCKS**, so the script simply hangs |
  The third one cost a run: `tell application "Finder" to close every window`
  hung for the full timeout on the FIRST case and a propagating
  `TimeoutExpired` lost the whole run. macOS **refuses synthetic clicks on
  consent prompts by design**, so a person has to answer it — use
  `mac_eyes dialogs`, which screenshots whatever is waiting. Wrap every
  `osascript` call so a hang degrades that one check instead of the run.

> **The macOS 26 run is UNFINISHED.** What remains, with the state and the
> recipes needed to resume it, is in **`MAC_AUDIT_CONTINUE.md`** beside this
> file. Read that before starting a fresh macOS session.

## What the macOS 26 (Tahoe 26.6) run settled — 2026-08-11

Run `20260811_155557_macos-26-v2.0.2`. Read this before repeating any of it.

- **`is_macos_15_plus()` is TRUE on 26.6** (it compares the major), so every
  macOS-15 gate — the FDA nudge, the App Data story — is live on Tahoe.
- **M1 Office**: all three converters correct on real legacy binaries; the delete
  gate was OBSERVED firing (an empty .pptx made PowerPoint write a 0-byte PDF,
  which `pdf_looks_real` refused, keeping the original); a corrupt .doc kept the
  original byte-identical after a bounded 120 s -1712; CR / quote / backslash /
  240-byte / Danish+emoji filenames all convert and land under their true names;
  `quit_idle_office_apps` took 3 apps to 0, so the open Windows EXCEL.EXE leak
  does **not** reproduce here; no stale Dock document tile.
- **M2 Panopto**: 36 recordings discovered from module launches with **zero**
  media handshakes (Shortcut-only run); all 36 `.webloc` valid 2-key plists that
  Finder/Launch Services really opens; the Canvas ExternalTool collision resolved
  to `<title> (Panopto).webloc` beside the Canvas link, 36 + 41 = 77 on disk;
  `converters/url.py` consumed the 41 Canvas links and spared all 36 of ours;
  transcription runs on the Apple-silicon CPU out of process, and a mid-run
  cancel left **no `.part` and no worker**.
- **M3 bundle**: renders correctly in WKWebView (login + course list at parity
  with Chrome); the transcription worker is routed by env, confirmed by its own
  `routed_via=env` log line; one process, no `duplicate_launches.log`; exactly
  one SESSION END per START, so the macOS-15 double-close is fixed.
  - **One white frame at ~2 s on the FIRST launch of a freshly built and signed
    bundle**, not reproducible on any later launch (28 frames at 0.25 s were all
    dark, peak luminance 31.4, splash rendering as designed). Recorded rather
    than characterised — if you are on a fresh machine, sample the very first
    launch before anything else, because that is the only chance to see it.
- **M4**: a real product defect, fixed — `_probe_case_insensitive` flipped the
  DIRECTORY, whose name lives on its PARENT volume, so at a mount point it
  probed `/Volumes` (case-insensitive) and answered True about a case-SENSITIVE
  drive. See commit 91c7c58.
- **Checker**: `mac_eyes dialogs` cried wolf on Tahoe's phantom alert, which
  carries the title "Screen Recording" where macOS 15's was untitled (13c70c7);
  and the harness answered the Panopto notice BEFORE the click that raises it,
  which stalls any Panopto row on a fresh config dir (56fa5f6).
- **Second pass, same day**: the mp3 media path is DONE - all 36 recordings,
  0 decode failures, 0 leftover `.part`, and total duration **8.21 h / mean
  13.7 min, matching the macOS 15 mp4 run of the same recordings exactly**,
  which is the check a decode pass cannot make. The Keychain write / re-store /
  update / delete cycle is DONE through `store_token`. **Reveal in Finder needs
  no Automation grant** - `reveal_in_folder` uses `open -R`, a Launch Services
  call, not AppleScript; if you see a consent prompt there it is your own
  cleanup script, not the product.
- **A full seeded Phase 2 sync ran on macOS** (44 fixtures, 21 kinds). The app
  was correct in every case examined - the edited copy came through
  byte-identical with the fresh one forked to `_NewVersion` - and produced TEN
  highs, EIGHT of which were the checker matching files BY NAME. Fixed in
  aade2c0; one of them (`_name_candidates`' lowercase prefix list vs `normcase`
  being the identity off Windows) had made the whole secondary-entity half of
  that matcher dead on macOS.
- **Still not covered**: the folder-picker MODAL (blocks on a human; the return
  path was proven on macOS 15), and a real notification DENIAL in the bundle -
  finding fp:3833d3d15043 stays open, though M3 settled the half that was
  previously impossible by showing the bundle registers under its own identity
  rather than as "Python".

## The second install (macOS 26)

Everything above, in the same order, on the newer OS. Expect the differences to
cluster in exactly three places: **TCC wording and prompt behaviour**,
**notification delivery**, and **WKWebView rendering**. Re-run
`scripts/mac_audit_bootstrap.sh`; it is idempotent and should take minutes.
Carry `~/mac_audit_secrets.env` across so the Keychain and settings are seeded
without retyping anything.


---

## Notifications on macOS 26: the osascript fallback DELIVERS but does not BANNER (2026-08-20)

Measured on macOS 26.6.1 (Tahoe, M4), run `20260820_143238_macos-26-v2.0.2`,
with the screen confirmed clear of consent prompts first (`mac_eyes dialogs`) -
prompts sitting in the top-right corner are what invalidated the 2026-08-11
attempt, because that is exactly where a banner would appear.

**The question changes shape once the code is read.** `_show_macos_notification_un`
already refuses to fall back on an explicit denial (`_un_error_is_denial` -> log
once -> `return True`, meaning "the question is settled"). So the app NEVER
reaches osascript while denied - that was settled by 588bead, product owner's
call. The fallbacks run only on a NON-denial failure, and that is the case worth
measuring.

**What osascript actually does.** Screenshot diff (PIL `ImageChops.difference`
+ `getbbox`), banner region isolated, sampled at 0.4 / 0.9 / 1.6 / 2.6 / 4.0s:

    topright bbox = None at every sample, 0 changed pixels

Re-run after the operator enabled notifications: still no banner. (The pixel
delta that appeared at 1.8s/3.0s was a VS Code redraw - the saved crop shows an
editor, not a notification. **Always look at the crop before believing a
bbox.**)

**But it is delivered, not dropped.** The operator opened Notification Center
and photographed it: every probe present, grouped under a header reading
**"Script Editor"**. That is direct visual confirmation of the identity
objection the product decision rests on, which until now was only reasoned - a
user really would see `Script Editor: Sync done - 12 new files` attributed to an
app they never ran.

**CONFOUNDER, STATED RATHER THAN RESOLVED.** The operator is on NoMachine and
raised it unprompted: a remote desktop may route banners straight to
Notification Center without the popup. This session could not rule that out. The
positive control needs an app with its OWN bundle identity to banner
successfully in the same session; the packaged app now has that identity (the
launch prompted, the operator allowed, Alert Style = **Temporary**), but making
it post requires driving a run to completion.

    TRUE            the fallback is not inert - it delivers a persistent entry
    TRUE            the entry is attributed to Script Editor (photographed)
    TRUE            the app attempts no fallback at all while denied
    NOT ESTABLISHED whether osascript can banner on a LOCAL macOS 26 session

Do not restate the banner claim as fact in either direction until someone
measures it at the physical machine.


---

## WKWebView spot-check of what shipped AFTER the macOS 26 audit (2026-08-20)

The 2026-08-11 run could not cover this: the dismissible transcription-setup
notice (2026-08-19) and the conditional-`<style>` fixes (2026-08-20) did not
exist yet. The second matters most here, because it changed **which style hosts
exist and in what ORDER**, and both were verified only in Chrome over CDP. The
shipped app renders in **WKWebView**.

Built and ad-hoc signed on this machine (`--verify --deep --strict` rc=0,
`apple-events` entitlement intact), launched with
`open --env CANVAS_DL_CONFIG_DIR=...` pointed at a copy of the run's config so
it restored a real session through its own code path.

**All three targets render correctly.**

* **Course list** - two-line rows, Favorites/All segmented toggle, the live
  `0 of 14 selected` count (the one-cell grid with the hidden ghost sizer),
  Select All / Clear Selection, search, and the sticky action bar with
  Custom Download / OR / Quick Download.
* **Sidebar** - nav with the active item lit, Settings, `Logged in as Birk`,
  logout, `v2.0.2`, Support the project.
* **Step tracker** - both flows correct (`Select Courses / Configure Download /
  Analyzing / Downloading / Complete` and `Select Courses / Analyzing / Review
  Changes / Download & Sync / Complete`).

**The transcription notice's full cycle, which is the branch flip the
conditional-`<style>` rule is about.** Driven with real clicks:

    card (amber, 105px)  --click X-->  one-line link (~19px)  --click link-->  card

Nothing below it was left behind at any step: the action row moved up and back,
the card returned to the same geometry, and no stylesheet was lost - which is
precisely the failure mode (a branch flip shifting every LATER stylesheet onto
its neighbour's host) that the fix addresses. The `pad_slot_children` 2-child
padding reconciles correctly in WebKit.

**The dismissal persists and does not clobber the file.** After dismissing,
`canvas_downloader_settings.json` gained `transcription_setup_notice_dismissed:
true` with **all ten pre-existing keys intact** - an end-to-end confirmation of
the settings co-ownership hardening in the packaged app, not just in unit tests.

### Driving a WKWebView from the agent - what works

* `osascript`/System Events needs **Accessibility**, which this app deliberately
  never requests. Granting it to the terminal app is a decision for the
  OPERATOR, and it does not take effect for already-running processes - the
  grant landed but every `osascript` still returned `-25211` because VS Code
  had not been restarted.
* Even with access, `System Events ... click at {x,y}` returns **-25208** here.
* What works is a **CoreGraphics event**: `CGWarpMouseCursorPosition` then
  `CGEventCreateMouseEvent` down/up posted to `kCGHIDEventTap` (PyObjC's
  `Quartz` is already available). A WKWebView has no AX tree to address
  element-wise, so coordinates are the only handle - take a `screencapture`
  first and read them off it. On this 1920x1080 display the capture maps 1:1.
* `mac_eyes shot --window "Canvas Downloader"` matches by TITLE, and **VS Code's
  own window title contains the same string**, so it silently captured the
  editor. Activate the app by PID and take a full-desktop shot instead.

### The Keychain prompt on a rebuild is real, and it BLOCKS

Launching a freshly ad-hoc-signed bundle that reads the previous build's
Keychain item raises *"Canvas Downloader wants to use your confidential
information stored in 'CanvasDownloader'"*, with **Always Allow / Deny / Allow**
and a password field. It blocks the app's session restore until answered, and
macOS refuses synthetic clicks on it by design - screenshot it and ask the
operator. This is the prompt `CLAUDE.md` predicts under "Keyring"; it is
expected on a rebuild and does not affect a released build a user installs once.


### The sync REVIEW notice, live at last (2026-08-20)

`CLAUDE.md` recorded this as *"never verified live - unit tests only"* on ANY
platform. It now is, in the packaged app on macOS 26.6.1.

**Getting there is the hard part, and it is worth writing down.** The notice
counts recordings that are ACTIONABLE and carry `txt`/`srt` in their
`download_kinds` (`ui/sync_review.py:_tx_recording_count`), so it needs:

1. a pair pointed at a course that really has Panopto recordings (43660 has 36);
2. that folder's stored `panopto_contract` asking for `output_txt`/`output_srt`
   - seed it with `SyncManager._save_metadata('panopto_contract', ...)`, since
   no UI edits a folder's contract;
3. an **EMPTY** folder, which is what makes every recording actionable rather
   than up-to-date.

Result: 246 new files, 36 recordings, analysis complete in under 45s including
the 36 LTI handshakes, and the card reads

    Transcripts & Subtitles need a one-time setup
    36 pending recordings are set to produce Transcript or Subtitle files.
    No transcription model is installed yet. ...
    [ Set up transcription ]

**The `dismissible=` split is confirmed on the one thing only a live run could
show.** With `transcription_setup_notice_dismissed: true` already on disk (set
by dismissing the sync-LIST card earlier in the same session), the two call
sites diverged exactly as designed: the sync list rendered its **one-line
link**, the review screen rendered the **full card with no dismiss control**.
Same flag, same session, same process - so this is the per-call-site decision
working, not two copies that happen to agree.

Note the powerbox prompt: a course folder outside the app's own container
(here, under `/tmp`) raises *"Canvas Downloader would like to access data from
other apps"* on first access. macOS ignores synthetic clicks on it - screenshot
it and ask the operator.


### iCloud "Optimize Mac Storage" - the method, and the traps (2026-08-20)

An iCloud account was created on the audit box for this; the previous two runs
had none, which is the only reason it stayed open. **iCloud is supported** - see
`CLAUDE.md` for the verdict and the contract tests. This is how to re-measure it.

    fresh file          st_size 124009  st_blocks 248   dataless False
    after brctl evict   st_size 124009  st_blocks 0     dataless True
    compute_local_md5   CORRECT hash, 0.9-1.35 s
    after the read      st_size 124009  st_blocks 248   dataless False

Then, driving the REAL `SyncManager` on a fully evicted 10-12 file folder:

    analysis, nothing changed on Canvas    0 materialised
    analysis, ONE genuine update           1  (only the changed file)
    heal_manifest after a RENAME           1  (only the renamed file)
    os.replace onto a dataless target      OK, content correct

**Detect dataless with `st_blocks == 0` at a nonzero `st_size`.** Do NOT use
`brctl status`: on a freshly-enabled account it returns *"Client zone not
found"* for a path that is plainly there, which reads like a broken test rather
than an uninitialised zone. That is brctl failing to QUERY, not the file being
unsynced - proved by evicting (blocks 248 -> 0) and reading the correct md5 back
in 0.89 s, which can only have come from the cloud copy.

**A test fixture must change the SIZE, not just the timestamp.** `_is_canvas_newer`
deliberately treats same-size-newer-timestamp as a metadata touch and returns
False, so a timestamp-only "change" produces no update at all. The first version
of this measurement fooled itself exactly that way and nearly recorded "0
materialised on an update" as a good result.

**Measure the failure case by its CONSEQUENCE, not by going offline.** This
machine is reached over NoMachine, so cutting the network strands the operator
and the agent. Make the read fail (`chmod 000`) and ask the real primitive:
`compute_local_md5` returns `None` and `_classify_local_modification` answers
**`modified`** - the `_NewVersion` fork, the documented deliberate bias
("preserve the local copy"). An unmaterialisable file costs a sibling, not an
overwrite. A real materialisation failure remains unmeasured; only its
consequence is.

`tests/test_icloud_dataless.py` pins the properties that make all of this work,
portably (it counts `compute_local_md5` calls instead of needing iCloud), and
`scripts/_mutate_icloud_dataless.py` proves those tests can fail - 5/5.

## Transcription on Apple silicon - M2.5, M2.6 and M3.3 settled (2026-08-20)

The whole transcription subsystem had never run on a Mac. It does now, on macOS
**26.6.1 / M4 arm64**, in both the dev tree and the packaged bundle. Nothing was
found wrong with it; what follows is what "works" actually means, so the next
session does not re-derive it.

**Hardware detection is calm and correct.** `detect_compute_hardware()` returns
in **0.09 s** with `status: cpu_only_mac`, `gpu_available: false`, cpu "Apple
M4" / 10 cores, CT2 CPU compute types `{int8, int8_float32, float32}` -> picks
`int8`. It recommends **Small** and deliberately omits the "a GPU would allow a
larger model" upsell, which is right: the engine has no GPU backend on macOS at
all, so no GPU a Mac user could buy changes the answer. `device_advisory` warns
for medium / turbo / large-v3 and stays silent for tiny / base / small.

**The measured speed table in `panopto/models.py` transfers.** 577 s of real
speech transcribed in **95.8 s = 6.0x realtime** on `small` - against the 6.2x
recorded there for an M4. That table is what stops Turbo being recommended on a
Mac, so it is worth knowing it is still accurate.

**Model download**: `start_download("small")` fetched 4 files / **486 MB in
5.5 s** into `panopto_models/small`, reached terminal state `done`, and flipped
`transcription_status()` to `ready: true` - which is the half that clears the
setup notice. Note the progress denominator is the registry's `size_mb`
(507.5 MB against 486.2 MB actual), so the bar tops out near 96 % and then
jumps; that is the documented "approximate" denominator, not a defect.

**The out-of-process design does its job.** Verified by sending a real
**SIGSEGV** to a live worker - the closest thing to the uncatchable native crash
the subprocess exists for:

| | |
|---|---|
| parent | survived, raised `TranscriptionEngineCrash(exit_code=-11)` |
| worker | reaped, no orphan |
| stderr | faulthandler C-level traceback, mirrored into the parent's log |
| `.part` | **left on disk** - see below |

The abandoned sidecars are NOT a defect, because the phase-level `finally` in
`panopto/runner.py` sweeps every task on the way out and there is exactly one
production caller. That count is now a test (`CLAUDE.md` has the mechanism).

**Cancel mid-transcription is clean, with a positive control.** The `.part`
sidecars were confirmed present at 4.9 s, cancel took effect **0.1 s** after the
flag, `PanoptoCancelled` was raised, **0 `.part` files remained**, no partial
output was promoted, and the worker was reaped. That is the 2026-08-09 `finally`
fix verified on a Mac for the first time.

**M3.3 - the argv drop is genuinely fixed.** Driving the bundle's console worker
with the env var ONLY and no argv flag:

    worker start: pid=27989 frozen=True routed_via=env device=cpu ...

`routed_via=env` is the proof, and the presence of that line at all is the
documented tell that routing worked (its ABSENCE means the child booted the
GUI). The frozen run produced **byte-identical** output to the dev run (9869 B
txt / 10881 B srt, 30 segments, 95.7 s vs 95.8 s), which also proves
faster-whisper, ctranslate2 and onnxruntime all load from the arm64 bundle.
Exit 0, no `.part`, and only ONE `Canvas_Downloader` GUI process throughout.

**Zero Dock footprint, confirmed.** With a frozen worker alive, `mac_eyes dock`
showed `recent-apps` holding only Visual Studio Code - before, during and after
the worker was killed - and System Events listed no worker among the non-
background applications. The console-bootloader choice in `_worker_command()`
is doing what its comment claims on macOS 26.

**One thing the operator should expect, and it is cosmetic**: a worker that dies
natively raises macOS's own *"Python quit unexpectedly"* crash-reporter dialog
(in a packaged build it would name `Canvas_Downloader_Worker`). The app is fine
and handles it - but the OS announces it regardless, and nothing in-process can
suppress ReportCrash. Do not read that dialog as the app crashing.

## M1.3 - forcing a conversion failure, live against real Word (2026-08-20)

The macOS delete gate (`pdf_looks_real` on the AppleScript branch) had only ever
been driven by SIMULATION - `sys.platform` patched to darwin with the bridge
stubbed to leave a 0-byte file. This is the first time real Word has been made
to fail on a Mac and the folder inspected afterwards.

**Setup that works, and why each file is there.** `textutil -convert doc` makes
a genuine legacy `.doc` (the runbook's own trap note - do NOT try to build one
by driving Word). Four unconvertible siblings, ordered AFTER the good one so a
success resets the repeat counter first:

| file | how | what Word does |
|---|---|---|
| `good.doc` | `textutil -convert doc` | converts - the CONTROL |
| `garbage.doc` | 4 KB `/dev/urandom` | hangs, then `-1712` timeout |
| `truncated.doc` | first 200 B of `good.doc` | modal, `-30001` |
| `empty.doc` | 0 bytes | modal, `-30001` |
| `pretend.doc` | plain text | never reached (skipped) |

**Result - every property holds:**

    success 1  failure 4        systemic_failure() -> ('Word', 3)
    good.doc   GONE -> good.pdf (7890 B, real PDF)
    garbage / truncated / empty / pretend  ALL UNCHANGED
    stub PDFs in the folder: NONE

So the source-survival gate works against real Office failures, and the product
gate refused to promote every failed output. Reproduced twice, identically.

**The abort is ONE message, and its diagnosis is TRUE.** Three per-file errors,
then the phase ended with a single line:

> Microsoft Word failed on 3 files in a row with the same error (...). It is
> most likely waiting on a dialog and will not convert anything else this run.
> Quit Microsoft Word and run again to convert the rest. - skipping remaining 1
> Word file(s)

That claim was checked against the screen rather than believed: System Events
reported Word holding exactly one window, `subrole=AXDialog`, titled
**"File Conversion - src_efb781.doc"** - the encoding picker. O2 and O3 agree.
The staged name also confirms the `src_<6 hex>` unique-basename fix is live.

**The teardown recovers a modal-wedged Word**: `quit_idle_office_apps()` in the
same process quit it in **12 s** while it sat on that alert holding our staged
document. So "run again" works with no user action - the instruction is
redundant when Word was ours, and necessary when it was the user's, which is
the direction that matters.

**THE HARNESS TRAP THAT NEARLY BECAME A FINDING.** Calling
`quit_idle_office_apps()` from a FRESH interpreter logs
`Microsoft Word -> left alone (we never drove it this run)` and quits nothing -
correctly, because `_office_preexisting` is process-local per-run state and a
new process has observed nothing. That reads exactly like the gate failing. Any
teardown check must run in the SAME process as the conversions.

Second trap: `run_word_conversion` needs a real `SyncManager` in its file
tuples. Passing `None` raises inside `_update_manifest_path` AFTER the source
has already been deleted.

## M2.3 / M1.5 / M1.6 - shortcuts, Office leak, Dock tiles (2026-08-20)

### M2.3 - "compile widely, delete narrowly", proven on macOS

`converters/url.py` reads BOTH shortcut formats and deletes only this
platform's own. Driven live with a folder built by the real
`shared.shortcuts.write_shortcut`, so the bytes on disk are the app's own
format - a `.webloc` two-key plist (`URL` + `CanvasDownloaderSource`) and a
`.url` whose marker sits in its own `[CanvasDownloader]` INI section, exactly as
the module docstring specifies.

| file | expected | result |
|---|---|---|
| plain `.webloc` | compiled **and deleted** | as expected |
| plain `.webloc`, nested a folder deep | compiled and deleted | reached by `rglob` |
| `Lecture 1 (Panopto).webloc` (our marker) | kept, never compiled | as expected |
| `Lecture 2 (Panopto).url` (our marker, foreign format) | kept, never compiled | as expected |
| plain `.url` written on WINDOWS | compiled but **KEPT** | as expected |
| `file://` shortcut | kept, never compiled | as expected |

**Idempotent over repeated runs**, which is the property the surviving foreign
`.url` makes load-bearing: it is re-read on every pass, so a dedupe miss would
grow `Compiled_External_Links.txt` for ever. Three passes -> nothing further
deleted, **exactly one** occurrence of the Windows link, file size stable at
394 bytes.

### M1.5 - no Office leak

After a real Word phase plus the in-process teardown,
`pgrep "Microsoft (Word|Excel|PowerPoint)"` is **empty**. A plain
`quit saving no` also lands cleanly. The leaked-`EXCEL.EXE` finding is a
Windows shape; the Mac does not share it.

### M1.6 - Recents: TWO different stores, and the first check read the wrong one

**CORRECTED the same day, by the operator noticing what the check could not.**
The first pass reported "0 tiles of ours" from `defaults export com.apple.dock`
and called M1.6 clean. Then the operator opened Word and found its start-screen
Recents full of our staged `src_*` files.

Both statements were true, because they are **different stores**:

| store | holds | read with |
|---|---|---|
| Dock tiles | the Dock's own recent-apps / recent-documents | `defaults export com.apple.dock` (`mac_eyes dock`) |
| **Office Recents** | what Word/Excel/PowerPoint show on their start screen | `~/Library/Group Containers/UBF8T346G9.Office/MicrosoftRegistrationDB.reg`, table `HKEY_CURRENT_USER` |

`purge_stale_self_dock_tiles` is about the FIRST; the thing a user actually
sees after a conversion phase is the SECOND. **Measure the Office registry**
- `scripts/verify_office_end_to_end.py:_recents_ours()` already does, and it is
the check to reuse.

**The purge itself is correct, and it clears the BACKLOG.** Measured with 10 of
our entries accumulated across the day's runs:

    recents_ours_before: 10  ->  recents_ours_after: 0     VERDICT: ALL GOOD

It matches on the marker (`CanvasDownloaderTmp`), so a single later run cleans
everything left by earlier ones - the entries do not need the run that made
them. The staged temp dirs are gone too, so those Recents rows point at files
that no longer exist, which is exactly the condition the purge exists for.

**Why the backlog existed at all - both reasons are harness, not product:**

1. Ad-hoc conversion scripts that never call `quit_idle_office_apps()` leave
   the entries, because the purge is part of the TEARDOWN.
2. The purge **declines for a RUNNING app**, by design - an entry would be
   resurrected from that app's in-memory list on exit. So with Word open
   nothing is cleaned, and that is correct rather than a stall.

Combined with the fresh-interpreter trap in M1.3, a purge check has THREE ways
to report a false failure: wrong store, wrong process, app still running.

Two things NOT to misread here. A `Microsoft Error Reporting` entry appears in
`recent-apps` after you **`pkill`** a wedged Word - it is Microsoft's app, not a
Canvas Downloader tile, and the app's own graceful teardown does not produce it.
And Word being alive after a bare conversion script is the harness, not a leak:
the teardown only runs if you call it, in the same process (see M1.3).

### M1.3, second half - the Automation revoke is NOT PROVABLE mid-session

Revoking Automation for Word in System Settings had **no effect** on a run
already in flight: five genuinely convertible `.doc` files still converted in
3.9 s, and a bare `osascript ... tell "Microsoft Word"` still succeeded. macOS
caches the TCC decision in the RESPONSIBLE process, which here is the long-lived
editor, so a mid-session revoke reaches nothing this agent can spawn. A probe
against a never-used target (Calculator) did not prompt either, so this client
already carries broad grants.

Proving it needs a client with no cached decision - i.e. do it as the FIRST
action after a fresh login, or from a Terminal whose grant is then cleared with
`tccutil reset AppleEvents com.apple.Terminal`. Restarting the editor would kill
the agent session.

What that leaves unproven is narrow: whether macOS's real denial wording reaches
`_classify_stderr`. The classification itself is unit-tested in BOTH directions
(`tests/test_office_crash_is_not_missing.py`), and the abort it triggers is the
SAME function the systemic path uses - which was verified live in M1.3's first
half, one message and all remaining files skipped. So the untested step is a
string match, not the machinery.

## M1.7 - long paths, and the component limit is UTF-16 UNITS (2026-08-20)

**The runbook's own premise was wrong, and so was `AUDIT_FINDINGS.md` - in
opposite directions.** This file said "255 BYTES per component"; the findings
register said "255 CHARACTERS, not bytes". Measured by writing real files on
APFS, neither is right:

| name | UTF-16 units | bytes | chars | result |
|---|---|---|---|---|
| 255 x `a` | 255 | 255 | 255 | OK |
| 256 x `a` | 256 | 256 | 256 | ENAMETOOLONG |
| 255 x `æ` | 255 | **510** | 255 | **OK** |
| 127 x emoji | 254 | 508 | 127 | OK |
| 128 x emoji | 256 | 512 | **128** | ENAMETOOLONG |
| 253 x `æ` + 1 emoji | 255 | 510 | 254 | OK |
| 254 x `æ` + 1 emoji | 256 | 512 | 255 | ENAMETOOLONG |

The limit is **255 UTF-16 code units**. APFS stores names as UTF-16, and an
astral character (emoji, CJK extension B, historic scripts) is a surrogate pair
- two units for one Python character. NTFS counts the same way, so this is not a
macOS quirk to guard on one platform.

**Why it matters even though nothing is broken today.** The app's cap is
expressed in CHARACTERS (`_sanitize_filename(..., max_length=120)`), the
filesystem's in UNITS, and the worst-case ratio is 2:1. Measured worst output:
**236 units** against a 255 ceiling - a margin of 19, about ten emoji. Raising
the cap past **127** would make an all-astral Canvas filename illegal on both
platforms, and it would fail as ENAMETOOLONG at download time, i.e. as a MISSING
FILE rather than a visible error. Pinned by
`tests/test_sanitize_filename.py` + `scripts/_mutate_filename_utf16_cap.py`
(4/4 caught, including the plausible "raise it to 200 to preserve longer names").

**`office_safe_path` does nothing here.** `shared/helpers.py` returns the
pass-through branch on any non-Windows platform, by design and with a comment
saying so - it exists for Win32 COM. macOS length is handled by
`office_container_stage`, which stages EVERY conversion under a short
`src_<hex>.<ext>` name regardless of the source's length.

**Driven live, and it simply works:**

    442-char path, 240-unit filename component  ->  converted in 1.6 s, real %PDF-
    900-char path                               ->  converted in 0.9 s, real %PDF-

both with the source removed and the PDF landing at the long destination. Going
past ~900 needs more directory LEVELS, not a longer name - the two limits
interact, since the component itself cannot exceed 255 units. Realistic worst
case in this app is ~410 chars (root + course + module + file, each capped at
120), so there is a wide margin.

## M3.3 / M3.4 / M3.8 - the packaged app (2026-08-20)

Run from `dist/Canvas Downloader.app` with `CANVAS_DL_CONFIG_DIR=/tmp/m34`, on a
baseline with every earlier instance killed.

**M3.4 - no phantom instance.** One process, one window
(`Canvas Downloader`, 1920x960 - it opens BEHIND the editor, so "no window" is
a false alarm; check `mac_eyes windows`, not the screen), one LaunchServices
entry with a bundle path, and **no `duplicate_launches.log`**.

`lsappinfo` additionally lists *"Canvas Downloader Networking"*, *"... Graphics
and Media"* and *"... Web Content"*. **Those are WebKit's own XPC split**
(`/System/Library/Frameworks/WebKit.framework/.../XPCServices/`), not instances
and not Dock icons - do not report them.

**M3.8 - quit and reap.** Quitting with a real Quit Apple event
(`tell application "Canvas Downloader" to quit`, which is what Cmd-Q sends):

    SESSION START ... 16:45:56Z
    SESSION END (clean)  uptime=114s peak_self=222.2MB
    clean_exit: True     children: []

That is **exactly one END for one START**, and a `clean_exit` marker on the
Cmd-Q route - the two defects `start.py`'s shutdown block documents (measured
2026-08-10: `clean_exit=False` after a graceful quit, and later two identical
END lines for one START). Both fixes hold on 26.6.1.

Afterwards: **0 leftovers**, the app's own WebKit GPU helper reaped, port 8501
released, `lsappinfo` reports no Canvas entry at all.

**What this does NOT prove**: the session spawned no ffmpeg or transcription
child, so only the WebKit teardown was exercised - not
`_terminate_child_processes` against a real media child. That needs a quit taken
DURING a Panopto download or transcription.

### Two counting traps that produce fake orphans

* `pgrep -f ffmpeg` **matches the shell running it**. Every "leftover" in a
  naive sweep was the probe itself. Enumerate `ps -axo pid,command` and exclude
  your own process explicitly.
* WebKit helpers with pids far BELOW the app's belong to other applications
  (the editor, Safari). Compare pids before concluding the app leaked one.

### Quitting needs no System Events

A direct Quit Apple event to the app works, so M3.8 does not depend on the
System Events grant. Useful, because that grant is exactly what a mid-session
Automation experiment takes away (see M1.3).

## M2.6 - the model manager, both switch states (2026-08-20)

Driven in the real app (isolated `CANVAS_DL_CONFIG_DIR`, the model symlinked in
so the config could be disposable). Settings is NOT reachable before login, so
this needs the keychain token - read it, never print it.

**Panopto ON, model installed:**

    status line : "Ready · active model: small"
    button      : "Manage transcription configuration"

**Panopto OFF, model installed** - the "do not strand the user's disk" case:

    status line : "Panopto is switched off · open to remove the installed
                   model or GPU libraries and reclaim the space"
    button      : "Manage installed models"
    is_enabled  : True      computed filter: none

That last pair is the check worth making: a correct LABEL on a DISABLED button
would defeat the whole purpose, since this dialog is the only place a
multi-gigabyte model can be deleted. It is genuinely live, and not painted with
the app's disabled recipe.

**The dialog itself, judged on screen:**

* Detected Hardware reads *"GPU - Apple Silicon - no GPU mode (the engine runs
  on the CPU)"* and *"CPU - 10-core CPU · Apple M4"*; the GPU device button is
  correctly unavailable.
* **Exactly ONE "Recommended" badge** (on Small) - the documented double-badge
  bug, where the registry flag and the UI's own computation both fired, stays
  fixed.
* Small shows **Active** plus a delete control; the other five show Download.

**Three model-size numbers, and they are NOT a divergence.** The registry
declares `size_mb: 484`, the row displays **464 MB**, and the download
denominator was 507.5 MB. The UI shows the declared size until a model is
installed and then switches to the MEASURED `installed_size_mb` - preferring
measured over declared, which is right. The denominator is the declared figure
in bytes, so the bar tops out near 96 % and jumps; `size_mb`'s own docstring
calls it approximate.

## M4.1 - HFS+ / NFD, and the case-only rename (2026-08-20)

Both halves of Phase M4's macOS additions, driven against a REAL HFS+ volume
(`hdiutil create -size 400m -fs "HFS+" -volname NFDTest`).

**How HFS+ actually stores Danish, measured by writing files:**

| name | HFS+ | APFS |
|---|---|---|
| `Årsrapport 2025.pdf` | **NFD** | NFC |
| `Résumé.pdf` | **NFD** | NFC |
| `Økonomi og ændring.pdf` | NFC | NFC |
| `Plain ASCII.pdf` | NFC | NFC |

Exactly the partial symptom `_path_key`'s docstring predicts: `å` and `é`
decompose, `ø` and `æ` have no decomposition and do not. A user with a course
folder on an external drive sees SOME files misbehave and not others, which is
what makes it read as random rather than as an encoding fault.

**Result - every file stays tracked, and the controls are not vacuous:**

| scenario | matched | orphans | untracked | untracked WITHOUT `_path_key` |
|---|---|---|---|---|
| NFD, HFS+ | 4/4 | 0 | 0 | **2** |
| NFD, APFS (control) | 4/4 | 0 | 0 | 0 |
| case rename, HFS+ | 1/1 | 0 | 0 | **1** |
| case rename, APFS | 1/1 | 0 | 0 | **1** |

The APFS column reading 0 for NFD is the point: it proves the HFS+ result is the
normalisation doing work rather than a test that could not fail.
`_case_insensitive_volume` answers True for both volumes (HFS+ is
case-insensitive by default), so the case fold applies on both.

### THE TRAP: `_path_key` must be given an ABSOLUTE path

A first version passed bare filenames (`_path_key("Notes.pdf")`) and reported
the case-only rename as UNTRACKED on both volumes - which reads exactly like a
missing fix. It is not: `_case_insensitive_volume` **deliberately refuses a
relative path**, because it would resolve against the current directory rather
than the course folder, and its own docstring says so. The real call sites join
the root - `_path_key(self.local_path / row['local_path'])` - and so must any
test. A relative-path check silently measures nothing.

Cleanup: `hdiutil detach /Volumes/NFDTest && rm /tmp/nfd.dmg`.

## The packaged-app run that closed M1.3, M2.1, M2.2, M2.4 and M3.8 (2026-08-20)

One real run of course 43660 inside `dist/Canvas Downloader.app` closed five
runbook items at once. **The technique is the reusable part.**

### Drive the PACKAGED app over HTTP, not with synthetic clicks

The bundle serves Streamlit on `127.0.0.1:8501`, and Streamlit runs the script
in the SERVER process. So a Playwright session pointed at that port executes
inside the packaged app: its children are the app's children and its Apple
events carry the app's TCC identity (`com.canvasdownloader.app`). That removes
the whole CoreGraphics-clicking problem the earlier sessions fought.

Two things make it work:

* **Reuse the live-audit harness's knowledge, do not restate it.** Import
  `TOGGLES`, `CARD_FOR` and `IS_ON_JS` from `tests/audit/harness/flows.py`. The
  settings are `st.button`s whose state lives only in CSS, and the rule is
  **"ON iff the border colour is CHROMATIC"** (`spread > 24 && alpha > 0.5`) -
  not a list of hexes, which this project's colour policing would rot. Toggles
  are addressed by KEY (`btn_convert_word`, `btn_pan_out_mp3`), never by text.
  A driver written from scratch rediscovers all of this badly - measured.
* **Each Playwright run is a FRESH Streamlit session**, so the app resets to
  step 1 and everything must happen in one script.

Traps paid for: a script named `select.py` shadows the stdlib `select` module
and playwright dies on a circular import; the course checkbox is clipped out of
the viewport by the list's scroll container, so use the app's own search to
narrow it and click via JS (`el.click()` on a real checkbox DOES fire React's
onChange); and the toggle labels contain a U+2B62 arrow that does not survive a
heredoc, so match by key, not by text.

### M1.3 CLOSED - Automation genuinely denied, in the real app

The operator clicked **Don't Allow** on `"Canvas Downloader" wants access to
control "Microsoft Word"` (the prompt carries the app's own purpose string from
`NSAppleEventsUsageDescription`). Result:

    [AppleScript] Word failed (permission): ... Not authorised to send Apple
                  events to Microsoft Word. (-1743)
    Klyngevejledning_1_Program_2023.doc  Conversion failed - macOS blocked
                  Canvas Downloader from controlling Microsoft Word (Automation
                  permission denied). Enable it in System Settings → Privacy &
                  Security → Automation → Canvas Downloader.

* classified `permission` -> FATAL -> abort, message names the exact Settings path
* **the original `.doc` survived** (153,600 B) and **no stub PDF** was promoted
* macOS really does emit the **BRITISH "authorised"**, confirming live the
  wording the classifier fix added the same day

It also exposed a defect - the abort was emitted TWICE because
`retry_failed_conversions` retried a fatal phase. Fixed; see the register
(`fp:6c1a2474d09e`).

**Afterwards run `tccutil reset AppleEvents com.canvasdownloader.app`** (and
`SystemPolicyAppData` for the powerbox), or the app is left denied.

### M2.1 / M2.2 / M2.4 CLOSED

    36 recordings discovered (38 LTI handshakes, all OK, source {'module': 36})
    36 mp3 in ~55s through the bundled arm64 ffmpeg
       (44100 Hz stereo 128 kb/s; 25:14, 10:52, 14:22 - real durations)
    77 .webloc: 0 malformed, all with a valid URL
       36 carry CanvasDownloaderSource=Panopto   41 are plain Canvas links
       ALL 36 of ours are '<title> (Panopto).webloc'

That last line is the documented Canvas-ExternalTool collision case firing **at
scale on real data**: every Panopto lecture is also a module item, so Canvas's
own link already owned the name and ours correctly took `(Panopto)` beside it
instead of overwriting.

**Finder really opens one**: `open <ours>.webloc` brought Safari forward on
`login.microsoftonline.com` - "Sign in with your CBS e-mail address" - i.e. the
shortcut reaches the real lecture behind institutional SSO.

### M3.8 CLOSED - with a REAL media child

Quitting mid-transcription (Quit Apple event, what Cmd-Q sends) with a live
`Canvas_Downloader_Worker` at 577 MB RSS:

    worker 42234                     -> reaped
    leftovers (ps -axo, excl. self)  -> 0
    SESSION END (clean) uptime=1128s peak_tree=1036.7MB
    clean_exit: True
    children: [{'pid': 42234, 'name': 'Canvas_Downloader_Worker', 'mb': 577.4}]

So `_terminate_child_processes` works against a real media child, not just the
WebKit teardown - the gap the earlier M3.8 pass explicitly left open.

### Two observations, neither a defect

* **A `.part` survives an app QUIT mid-transcription** (`<name>.txt.part`,
  2,695 B). The 2026-08-09 sweep lives in the transcription phase's `finally`,
  and a quit ends in `os._exit` without unwinding Python, so no `finally` can
  run. It **self-heals**: the mp3 remains, so the recording is a task again on
  the next Panopto run over that folder and the phase sweep removes it -
  verified by calling `_clean_part_files` on that exact file (1 -> 0). There is
  no clean fix at the shutdown boundary, which has no access to the session's
  course folders.
* **Quitting while a TCC prompt is pending records an UNCLEAN exit**
  (`PREVIOUS SESSION DID NOT EXIT CLEANLY pid=33358 phase='running'`). The
  same Quit Apple event records `clean_exit: True` when the app is responsive,
  so this is the modal blocking the Cocoa run loop rather than a shutdown
  defect. Not reproduced deliberately; recorded so the next session does not
  read it as a regression.

### The powerbox prompt re-arms EVERY PROCESS

`"Canvas Downloader" would like to access data from other apps` appears once per
app launch, and post-processing BLOCKS on it - measured, ~20 minutes of a run
sitting at the Post-Processing header with the app at 0% CPU. That is the
documented per-process re-arm, not a leak. Budget for it: every app restart
costs one more click, so enable debug logging BEFORE the run rather than
restarting to add it.
