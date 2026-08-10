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

## THE TRAP THAT COSTS HOURS: the Aqua session

macOS gives an SSH login a **Background** launchd session with no window
server. In it:

- `osascript` cannot drive Word/Excel/PowerPoint (Office conversions all fail),
- Playwright cannot open a headed browser,
- TCC prompts cannot appear (so grants can never be given),
- `pywebview` cannot create a window (the packaged app won't start).

Each fails differently and none of them says "you are in the wrong session".

```bash
launchctl managername      # must print: Aqua
```

**The fix is one habit**: start tmux from a Terminal on the Mac's own desktop,
then attach to it from SSH. The tmux *server* keeps the session it was born in
and every pane inherits it.

```bash
# on the desktop, once per boot:
cd ~/Canvas_Downloader && tmux new -s audit
# from SSH, any time after:
tmux attach -t audit
```

`scripts/mac_audit_doctor.py` checks this first and refuses to pass without it.

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
| Bundle: Info.plist, signature, **apple-events entitlement**, worker binary, **WebKit lookbehind patch**, boot splash, no tornado opener (`--bundle`) | M3 |
| No stray Canvas/ffmpeg processes; no duplicate GUI launches | M3 |

What it leaves out is anything needing eyes — **and you have eyes.**
`screencapture` runs from a plain shell, so `scripts/mac_eyes.py` reads the
real window server:

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
7. **Long paths.** `office_safe_path` shadows sources ≥240 chars. macOS allows
   1024-char paths but only **255 bytes per component** — a *different* limit
   from Windows, and one nothing has ever tested. Build a deep course folder
   and convert inside it.

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
    --detail "..." --evidence <path> --scenario mac_<id>
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

## The second install (macOS 26)

Everything above, in the same order, on the newer OS. Expect the differences to
cluster in exactly three places: **TCC wording and prompt behaviour**,
**notification delivery**, and **WKWebView rendering**. Re-run
`scripts/mac_audit_bootstrap.sh`; it is idempotent and should take minutes.
Carry `~/mac_audit_secrets.env` across so the Keychain and settings are seeded
without retyping anything.
