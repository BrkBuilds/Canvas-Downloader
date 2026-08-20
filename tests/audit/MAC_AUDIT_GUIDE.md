# macOS audit — the step-by-step

Written for a **bare rented Mac with nothing installed on it**. No IDE, no
Office, no Homebrew, no git. That is the actual starting point and the earlier
version of this guide wrongly assumed otherwise.

The agent's brief is `MAC_AUDIT_PROMPT.md`; what to test is `MAC_RUNBOOK.md`.

---

## How this works, in one paragraph

You **SSH in from your own PC** and run one setup script. It installs
everything (Xcode tools, Homebrew, VS Code + extensions, NoMachine, Microsoft
Office, Python, tmux) in 30-45 minutes, mostly unattended. Then you VNC in
**once**, to answer the consent prompts and grant NoMachine its two
permissions. From then on you work on the Mac's own desktop through
**NoMachine**: **VS Code running on the Mac**, with Claude Code in its
terminal.

**That last part is the workflow, and it is not merely a preference.** A VS
Code launched from the Mac's Dock is a child of the console session, so its
terminal is in **Aqua by construction**: the Keychain works, Office automation
works, TCC prompts appear in front of you, and none of the tmux gymnastics in
Part 4 applies. Remote-SSH from Windows puts you back in a *Background*
session where all three fail, each differently and none of them saying why.
Earlier versions of this guide recommended exactly that and it cost an
afternoon.

**What still needs a human at the screen:** answering consent prompts (macOS
refuses synthetic clicks on them by design), signing in to Office, and granting
Full Disk Access + Screen Recording. Roughly 10 minutes total.

---

# PART 0 — Before you rent (do this first)

### 0.1 Push your work

The macOS 15 audit is merged: **`main` is the trunk and carries every script
this guide names.** Nothing needs a special branch to get onto the Mac — the
Mac clones `main`. Branch on the Mac, for the fixes this run produces.

```bash
cd "G:/18 AI/ANTIGRAVITY WORKSPACES/Canvas Downloader"
python -m pytest tests/ -q                 # 0 failed
git status -sb                             # must be clean and level with origin
git push
```

**Push before you rent.** `mac_first_contact.sh` is fetched from `main` over
`curl`, so anything not pushed does not exist as far as the Mac is concerned.

### 0.2 On your Windows PC

- A **VNC client**. TigerVNC is known to work against macOS's ARD auth. You
  need it once, in Part 3, and only to grant NoMachine its permissions.
- The **NoMachine client**. This is what you actually work in all day.
- Your `mac_audit_secrets.env` (you have this).
- Microsoft 365 credentials to hand.

You do *not* need VS Code on Windows. The IDE runs on the Mac, and the setup
script installs it there.

---

# PART 1 — Rent

Scaleway → Apple silicon → **Mac mini M-series** → the OS this run is for →
**closest region**.

*Which OS:* every `is_macos_15_plus()` path — the Full Disk Access nudge above
all — is hard-gated to 15+, so it cannot render below it. **macOS 15 has been
audited** (2026-08-10; findings in `AUDIT_FINDINGS.md`). The run this guide is
now pointed at is **macOS 26 Tahoe**; see Part 6 for what to expect to differ.

Note the VNC address/password and the SSH user/IP.

---

# PART 2 — The setup script (SSH, ~40 min)

No desktop needed for this. From Windows PowerShell, or any terminal:

```bash
ssh m1@<mac-ip>
```

Then, on the Mac:

```bash
curl -fsSL https://raw.githubusercontent.com/BrkBuilds/Canvas-Downloader/main/scripts/mac_first_contact.sh -o ~/fc.sh
bash ~/fc.sh
```

> **Download it, then run it. NEVER pipe it into bash.** Piped, the script's own
> text is on stdin and `brew install` **reads stdin**: it swallows the rest of
> the file, bash hits EOF and exits **0**. Measured 2026-08-20, it stopped dead
> at the toolchain step having printed no error and no `[!!]`, so VS Code,
> NoMachine and Office never installed. The next half hour went on debugging a
> NoMachine "connection refused" that was really a script which had ended
> silently twenty minutes earlier. It fails as a *clean exit*, which is the most
> misleading way available.

It asks for your password once at the start and then runs unattended. In order:

| | |
|---|---|
| SSH on, sleep + auto-lock off | so you can leave VNC and the machine survives the day |
| Xcode Command Line Tools | installed **headlessly** via `softwareupdate` where possible |
| Homebrew | everything below depends on it |
| **VS Code** + Claude Code, Python, Remote-SSH extensions | your IDE, run **on the Mac** |
| **NoMachine** | the remote desktop you work in all day, port 4000 |
| **Microsoft Office** (~2 GB) | downloaded and installed for you |
| git, tmux, python@3.11, uv | the audit toolchain |

Go and do something else for half an hour.

### 2.1 When it finishes

Verify it reached the end rather than assuming it did. The failure mode above
is silent, so this is not ceremony:

```bash
ls -d "/Applications/Visual Studio Code.app" /Applications/NoMachine.app "/Applications/Microsoft Word.app"
sudo lsof -nP -iTCP:4000 -sTCP:LISTEN
```

Three paths and a listening `nxserver` means you are through.

---

# PART 3 — VNC once, then NoMachine for the rest

### 3.1 VNC in and answer the prompts

Any VNC client, from your own PC. **TigerVNC works** against macOS's ARD
authentication, so there is nothing to shop for:

```
<mac-ip>::59010          # host::port; the VNC port is on the Scaleway console
```

Click **Allow** on every dialog macOS raises, then grant NoMachine both of:

- Privacy & Security -> **Screen & System Audio Recording** -> **+** -> NoMachine
- Privacy & Security -> **Accessibility** -> **+** -> NoMachine

NoMachine can neither show nor control the screen without them, and **neither
can be granted from a command line**: no `tccutil` grant exists, and
`profiles install` for a PPPC payload needs MDM enrolment. That is the entire
reason VNC is still in this procedure.

### 3.2 Connect NoMachine

Host `<mac-ip>`, port **4000**, protocol **NX**. If the desktop comes up black
after granting, restart the server: `sudo /etc/NX/nxserver --restart`

Then drop VNC. Everything below happens in the NoMachine window.

### 3.3 Sign in to the apps, on that desktop

1. **Word** (`Cmd+Space`, "Word"), signed in with Microsoft 365. Installing
   Office does not licence it. Skip this and every conversion dies at a licence
   dialog and the whole converter phase reads as broken.
2. **VS Code**, granted **both**:
   - Privacy & Security -> **Full Disk Access** -> **+** -> Visual Studio Code
   - Privacy & Security -> **Screen & System Audio Recording** -> **+** -> Visual Studio Code

> **The Screen Recording grant goes to VS Code, not Terminal, and it is not
> optional.** TCC attributes a capture to the session's *responsible process*,
> which in this workflow is VS Code. Without it `screencapture` returns a bare
> desktop, and a blank capture is indistinguishable from a blank app: that is
> precisely how the last run nearly filed a CRITICAL against the packaged app's
> WKWebView rendering. `MAC_RUNBOOK.md` has the measured BLIND/capturable table.

### 3.4 Bring the secrets over

From a Windows terminal:

```bash
scp mac_audit_secrets.env <user>@<mac-ip>:~/
```

### 3.5 Clone and build the environment

Open VS Code **on the Mac**, `` Ctrl+` `` for a terminal, and:

```bash
git clone https://github.com/BrkBuilds/Canvas-Downloader.git ~/Canvas_Downloader
cd ~/Canvas_Downloader && ./scripts/mac_audit_bootstrap.sh
git checkout -b macos-audit-26        # this run's fixes go here
```

~15 min: the venv, every dependency, the pyobjc-UserNotifications pin CI uses,
Quartz, Playwright's Chromium, the settings file, the Keychain token (from your
`.env`, with a no-prompt ACL so nothing asks for a password mid-run), and
Claude Code.

**There is no `tmux attach` in this workflow.** That step existed only to drag
an SSH shell back into the graphical session, and VS Code on the Mac is already
in it. The console session also outlives a NoMachine disconnect, so VS Code and
anything it started keep running when you close the window.

### 3.6 Authenticate the agent

```bash
claude
```

Complete the browser sign-in. (Or use the Claude Code **VS Code extension**,
which the setup script installed — same thing, in the sidebar.)

---

# PART 4 — Verify before spending Mac time

```bash
cd ~/Canvas_Downloader && source .venv/bin/activate

python3 scripts/mac_aqua.py check        # keychain usable: True
python scripts/mac_audit_doctor.py       # until it prints READY
python scripts/mac_smoke.py --with-hfs   # ~2 min
```

The doctor probes window-server access directly (screencapture, System Events,
launching a GUI app). Do **not** gate on `launchctl managername == "Aqua"` -
it reports `Background` on a Scaleway Mac even when everything works.

**The Keychain is the exception to that, and it is the trap that cost an
earlier run its time.** It is scoped to the security session, not the
framebuffer, so a shell that drives the whole GUI can still be unable to create
an item of its own (`errSecInteractionNotAllowed`, -25308). Every Keychain
observation in the audit is then false rather than the product: the token save
"fails", auto-login "does not restore", the 90 s watchdog looks like it is
being hit.

```bash
python3 scripts/mac_aqua.py check       # session + Keychain, one line each
```

`keychain usable: True` is the gate. **In the NoMachine workflow it should
already be True**, because VS Code was launched from the Mac's own Dock and its
terminal inherits the console session. If it is False, the likeliest cause is
that you are running in a shell that arrived over SSH after all (a Remote-SSH
window, or a `tmux` server that was born over SSH). Work in the Mac-side VS
Code terminal instead. If you are mid-session and do not want to lose it, route
the command instead: Terminal.app is started by Launch Services inside Aqua and
every child inherits it, a long-lived Streamlit included:

```bash
python3 scripts/mac_aqua.py run "python -m tests.audit app start"
```

Then prove the harness works before trusting any result from it:

```bash
python -m tests.audit run new --label macos-26-v2.0.2
python -m tests.audit app start
python -m tests.audit browser open
python -m tests.audit canvas courses
python -m tests.audit canvas snapshot 43660
python -m tests.audit flow download smoke --courses 43667
```

---

# PART 5 — Run the audit

```bash
claude
```

Paste the whole of `tests/audit/MAC_AUDIT_PROMPT.md`.

### What is actually automated

The agent drives the real app through Playwright and reconciles five oracles.
It is not magic and it is not fully hands-off: it runs the scenarios, reads the
debug log, the manifest, the disk and the Canvas API itself, and takes its own
screenshots — including of the **real macOS desktop**:

```bash
python scripts/mac_eyes.py shot --window "Canvas Downloader"
python scripts/mac_eyes.py watch --seconds 20    # banners, splash, transients
python scripts/mac_eyes.py dialogs               # is something awaiting a human?
python scripts/mac_eyes.py dock                  # tiles whose target is gone
```

### Your job while it runs

**Answer TCC / Automation prompts.** macOS refuses synthetic clicks on consent
dialogs by design, so the agent screenshots the prompt and tells you which
button. Grant all three Office apps. That is essentially the whole of it.

Check in with `tmux attach -t audit`. For your own eyes, no desktop needed:

```bash
ssh <user>@<mac> 'screencapture -x /tmp/s.png' && scp <user>@<mac>:/tmp/s.png .
```

### Priority order

1. **M1 Office converters** — highest historical bug density.
2. **M2 Panopto** — never run on macOS at all.
3. **M3 the packaged `.app`** — the class the harness cannot reach.
4. **M4** matrices + the HFS+/NFD test.
5. **M5** notifications, folder picker, Keychain, Finder.

### 5.1 The packaged app

```bash
pyinstaller --clean Canvas_Downloader_macOS.spec
codesign --force --deep -s - --entitlements entitlements.mac.plist "dist/Canvas Downloader.app"
python scripts/mac_smoke.py --bundle "dist/Canvas Downloader.app"
open "dist/Canvas Downloader.app"
```

The one phase where NoMachine earns its keep: the harness drives **Chrome over
CDP**, the shipped app renders in **WKWebView**, so nothing CSS/JS is verified
until now.

### 5.2 Push

```bash
git add -A && git commit -m "macOS 26 audit fixes" && git push
```

**The Mac is rented. Nothing on it survives.** Push early and often.

---

# PART 6 — what macOS 15 already settled, and where 26 is likely to differ

The 15 run is done and its findings are in `AUDIT_FINDINGS.md`. **Do not
re-derive them.** This machine's value is the delta, so spend it where the OS
itself is the variable and a unit test structurally cannot reach:

| Area | Why 26 can differ | What a difference looks like |
|---|---|---|
| **TCC** | the prompt copy, the ordering, and which grant covers what have moved in every recent release | a prompt that never appears, or one that appears where 15 needed none — `mac_eyes.py dialogs` |
| **Notifications** | the `UNUserNotificationCenter` path is fallback #1 of 4 and the rest were already thinned | a delivered-but-invisible banner; verify by eye, not by return code |
| **WKWebView** | a new Safari engine renders the shipped app; the harness drives **Chrome over CDP**, so nothing CSS/JS is proven until 5.1 | layout that is correct in the harness and wrong in the `.app` |
| **Office** | a new Office build against a new OS is where the converter gates earn their keep | a `SaveAs` that returns clean having written nothing |
| **Keychain / session** | see Part 4 | measure it, never infer it |

The one rule that does not change: **a finding is a disagreement between two
oracles, and every finding names the pair.** Anything that worked on 15 and
misbehaves here is the most valuable thing this install can produce — and
anything that misbehaves on both is a product bug the 15 run missed, not a
Tahoe finding. Say which you are claiming.

---

# PART 7 — Teardown

```bash
python -m tests.audit report build
python -m tests.audit browser close
python -m tests.audit app stop
git add -A && git commit -m "macOS 26 audit fixes" && git push
```

Then **revoke the Canvas token**, destroy the instance, merge the branch.

---

# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Office conversions all fail / no window opens / no TCC prompt ever appears | No console session, so no window server | `stat -f%Su /dev/console` — if `root`, auto-login never completed: write `/etc/kcpassword` and reboot |
| Setup script stops at Xcode Command Line Tools | Headless install unavailable on this OS build | Accept the installer window, wait, re-run the script |
| Word opens but every conversion fails | Office installed but never signed in | Open Word, sign in with M365 |
| macOS asks for the login keychain password every run | Keychain item made without `-A` | `security add-generic-password -U -A -s CanvasDownloader -a "<url>" -w "<token>"` |
| Doctor: "Canvas token — absent" | No `.env` when the bootstrap ran | `scp` it over, re-run the bootstrap |
| Automation times out with -1712 | Automation not granted | Privacy & Security → Automation, or `tccutil reset AppleEvents` |
| Transcription segfaults | Known OpenMP clash | Must run in the subprocess worker — never co-load ctranslate2 with streamlit |
| Automation batch re-fires each run | Config dir isolated per run, so the app believes it is first-run | **Not a defect** |
| `ffmpeg -f null` calls every Panopto mp4 broken | Your null *muxer* on Panopto's duplicate DTS | **Not a defect** |
| Mac unreachable after a while | It slept | The setup script disables sleep; re-run it |

---

# The whole thing, as commands

```bash
# ── 1. SSH from Windows PowerShell. NEVER pipe this into bash. ──────
ssh m1@<mac-ip>
curl -fsSL https://raw.githubusercontent.com/BrkBuilds/Canvas-Downloader/main/scripts/mac_first_contact.sh -o ~/fc.sh
bash ~/fc.sh

# ── 2. VNC once (<mac-ip>::59010): click Allow on everything, then ──
#      Privacy & Security -> Screen Recording  -> + -> NoMachine
#      Privacy & Security -> Accessibility     -> + -> NoMachine

# ── 3. NoMachine: <mac-ip>, port 4000, protocol NX. Drop VNC. ───────
#      Sign into Word (M365). Grant VS Code Full Disk Access AND
#      Screen Recording. Then, in VS Code's terminal ON THE MAC:

git clone https://github.com/BrkBuilds/Canvas-Downloader.git ~/Canvas_Downloader
cd ~/Canvas_Downloader && ./scripts/mac_audit_bootstrap.sh

source .venv/bin/activate
python3 scripts/mac_aqua.py check          # keychain usable: True
python scripts/mac_audit_doctor.py         # READY
python scripts/mac_smoke.py --with-hfs

python -m tests.audit run new --label macos-26-v2.0.2
python -m tests.audit app start
python -m tests.audit browser open
python -m tests.audit canvas snapshot 43660
python -m tests.audit flow download smoke --courses 43667

claude          # paste tests/audit/MAC_AUDIT_PROMPT.md
```
