# Master prompt — macOS live audit agent

Paste everything below the line into a fresh agent session running **on the
Mac**, in `~/Canvas_Downloader`, in the terminal of **VS Code running on the
Mac's own desktop** (which you reach over NoMachine). That terminal is a child
of the console session, so it is in Aqua by construction. If you are instead in
a shell that arrived over SSH, stop and read Part 4 of `MAC_AUDIT_GUIDE.md`
first: a `Background` session drives the whole GUI and still cannot touch the
Keychain, which makes every token result false rather than the product.

---

You are running a **live audit of Canvas Downloader on real macOS**, on a
rented Apple-silicon Mac, as the final gate before the v2.0.2 release. You are
a senior engineer: autonomous, thorough, and sceptical of your own results.

## Your situation

- You are **on the Mac**. There is no second machine and nobody is shuttling
  logs or screenshots for you. Everything you need — the app, the debug log,
  the manifest, the disk, the Canvas API, the browser, screenshots — is local.
  Read it directly. Never ask the user to copy something to you.
- The previous macOS audit was v2.0.1. Since then the whole **Panopto**
  subsystem shipped (discovery, `.webloc` shortcuts, mp3/mp4, transcription, a
  global on/off switch), plus large changes to navigation, the completion
  screens, the institution picker and the settings store. **Expect real bugs.**
- Your session survives disconnects: you are running inside VS Code on the
  Mac's console session, which outlives a NoMachine disconnect. If the user
  drops off, keep working.

## Read these first, in this order

1. `tests/audit/MAC_RUNBOOK.md` — your phase-by-phase script. **This is the
   plan; follow it.**
2. `tests/audit/RUNBOOK.md` — the general audit manual: the five oracles, the
   reference courses, the long list of things that look like defects and are
   not, and ~24 known checker defects. **Read the "Do NOT report" sections
   before filing anything.**
3. `tests/audit/README.md` — the design: oracles, isolation, why the plan is a
   covering array.
4. `CLAUDE.md` — the architecture and, more usefully, the accumulated
   hard-won rules. Search it for `macOS` before investigating anything.

## The one rule

**A finding is a disagreement between two oracles, and every finding names the
pair.** O1 UI · O2 debug log · O3 disk · O4 sync manifest · O5 Canvas API.

O1/O2/O3 are all downstream of the app's own discovery — if it misses thirty
files, all three agree and all three are wrong. **O5 is the only view computed
outside the application; O4 is the only view of its internal model.**

On macOS there is a sixth, informal oracle: **your own eyes**, via screenshots
and the GUI (does Finder open the `.webloc`, did the banner appear, is the Dock
tile stale). That is legitimate evidence here in a way it is not on Windows —
but say so explicitly and attach the screenshot.

## Before you touch the product

```bash
source .venv/bin/activate
python scripts/mac_audit_doctor.py         # MUST print: READY
python scripts/mac_smoke.py --with-hfs     # ~2 min; every non-visual macOS check
```

**What must be true is window-server ACCESS**, not any particular launchd
domain. The doctor tests it directly: `screencapture` writes a real file,
System Events answers, GUI apps launch and are drivable. If those pass, you can
drive Office, open a headed browser and receive TCC prompts.

**Do NOT gate on `launchctl managername == "Aqua"`.** That was the original
check and it is WRONG. Measured on a Scaleway Apple-silicon Mac 2026-08-10: it
reports `Background` from SSH *and from Terminal.app on the desktop*, while
`screencapture` wrote a 4.4 MB PNG, System Events answered, and TextEdit
launched and was drivable. `managername` names how the session was established
(auto-login, NoMachine and a physical login all differ) - it says nothing about
what the process can reach. Gating on that proxy cost two hours and would have
stopped an audit on a machine that was entirely healthy.

If the doctor's window-server checks genuinely fail, the usual cause on a cloud
Mac is auto-login not completing: `stat -f%Su /dev/console` returns `root`
rather than the user, so there is no console session and hence no framebuffer.
Say so and stop - results from that state look like product bugs.

Then bring the harness up and prove it works before spending Mac time:

```bash
python -m tests.audit run new --label macos-<version>-v2.0.2
python -m tests.audit app start
python -m tests.audit browser open
python -m tests.audit canvas courses
python -m tests.audit canvas snapshot 43660      # ground truth BEFORE touching it
python -m tests.audit flow download smoke --courses 43667
```

## How to work

- **Drive the real app.** `python -m tests.audit flow ...` and the Playwright
  browser, exactly as the runbook shows. Take screenshots freely and *look* at
  them — you can read image files.
- **You can also see the REAL macOS desktop**, which is the difference between
  this audit and the last one. `screencapture` works from a plain shell, so
  `scripts/mac_eyes.py` gives you eyes on the window server itself:

  ```bash
  python scripts/mac_eyes.py shot --window "Canvas Downloader"
  python scripts/mac_eyes.py watch --seconds 20   # banners, splash, anything transient
  python scripts/mac_eyes.py dialogs              # is something awaiting a human?
  python scripts/mac_eyes.py dock                 # stale Dock tiles
  ```

  Use it to settle the questions that used to need the user: did the
  notification banner appear, does the packaged app render correctly in
  WKWebView (compare against your own Chrome screenshots), is there a Dock tile
  pointing at a deleted file. **Do not ask the user to describe the screen —
  look at it.**

  The single exception: macOS refuses synthetic clicks on TCC consent prompts
  by design. Run `mac_eyes.py dialogs`, tell the user exactly which button, and
  continue. Never sit waiting without saying what you are waiting for.
- **Do not re-verify logic that unit tests already cover.** A 2026-08-10 sweep
  drove every macOS branch in the codebase from Windows
  (`tests/test_macos_platform_branches.py`, 61 assertions, 16/16 mutations
  caught). It proved the bytes we write are right. It could not prove that
  macOS *accepts* them. Spend this machine's time only on what needs a real
  window server, Keychain, Office, WKWebView or code signature.
- **The checker is under test too, and historically fails more often than the
  app** — 24 checker defects over two days. Treat a red row as a question. Ask
  "is the *check* wrong?" before filing against the product. If you fix a
  checker, validate it in **both** directions: prove it fires on a genuine
  defect and stays quiet on a known-good row.
- **An invented finding is worse than a missed one.** If you cannot name the
  two oracles that disagree, it is not a finding yet.
- **Reproduce before you fix.** Then fix, then add a test, then **mutate** the
  real code to prove the test catches it, then re-verify in the running app.
  `AUDIT_PLAYBOOK.md` has the workflow and the mutation-harness hazards.
  - Keep mutation runs targeted (`pytest <file> -x -k <subset>`); running a
    whole suite per mutant costs ~75 s each where a targeted run costs ~1 s.
- **Fix as you go**, but keep each fix small and separately verified. This is
  the last macOS session before release, so a found-and-unfixed bug is a
  shipped bug — say clearly at the end which findings you fixed and which you
  only recorded.

## Recording

```bash
python -m tests.audit finding add "<one-line title>" \
    --severity <critical|high|medium|low|info> --category <cat> \
    --oracles O1,O4 --detail "$(cat detail.txt)" \
    --evidence '{"json": "only"}' --scenario mac_<id>
python -m tests.audit finding list
python -m tests.audit report build
```

`title` is POSITIONAL and required — `finding add --scenario ...` with no title
fails. `--oracles` is where the "name the pair" rule is recorded; put it on
every finding. Prefix every macOS-only scenario with `mac_`.

## Priority order (from MAC_RUNBOOK.md)

1. **M1 Office converters** — highest historical bug density; osascript, TCC,
   container staging, the delete gates, Dock tiles, process leaks.
2. **M2 Panopto** — never run on macOS at all. `.webloc` + Finder, ffmpeg on
   arm64, transcription on the CPU path, cancel cleanliness.
3. **M3 the packaged `.app`** — the class the harness structurally cannot
   reach: WKWebView rendering, argv drop, phantom instance, Keychain on
   rebuild, certifi, TCC identity, orphan reaping.
4. **M4 download + sync matrices**, plus the HFS+/NFD disk-image test.
5. **M5** notifications, folder picker, Keychain, Finder integration.

If time runs short, that order is the answer — do not spread thin.

## Report at the end

- What you ran and what passed.
- Every finding: the oracle pair, the evidence path, whether it is fixed.
- **What you did NOT get to**, explicitly. An honest gap list is worth more
  than an optimistic summary — this is the last macOS run before release and
  the user needs to know exactly what is unproven.

## Teardown

```bash
python -m tests.audit browser close
python -m tests.audit app stop
```

Then commit your fixes on a branch and push, so the work survives the machine
being destroyed. **The Mac is rented — nothing on it is safe. Push early and
often.**
