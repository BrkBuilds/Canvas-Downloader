# macOS audit — the step-by-step

Written for a **bare rented Mac with nothing installed on it**. No IDE, no
Office, no Homebrew, no git. That is the actual starting point and the earlier
version of this guide wrongly assumed otherwise.

The agent's brief is `MAC_AUDIT_PROMPT.md`; what to test is `MAC_RUNBOOK.md`.

---

## How this works, in one paragraph

You type **one command** in Scaleway's VNC console. It installs everything —
Xcode tools, Homebrew, VS Code + extensions, Microsoft Office, Python, tmux —
and takes 30-45 minutes mostly unattended. Then you leave VNC for good and work
from **VS Code on your Windows PC connected over Remote-SSH**: the editor is
local and instant, the files and terminal are the Mac's. The agent runs in that
terminal, on the Mac, and can see the Mac's screen with `screencapture`. That
is what removes the shuttling.

**Three things need the Mac's own screen and cannot be automated:** signing in
to Office (licensing), granting TCC permissions, and pressing the button on a
consent prompt. Roughly 10 minutes total.

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

- **VS Code** with the **Remote - SSH** extension. This is your IDE for the
  whole day — install it now, not on the Mac.
- Your `mac_audit_secrets.env` (you have this).
- Microsoft 365 credentials to hand.

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

# PART 2 — The one command (VNC, ~40 min)

Connect with Scaleway's VNC console. It will be slow. You are here once.

**Open a terminal:** press `Cmd+Space`, type `Terminal`, press `Return`.

**Paste this and press Return** (paste is `Cmd+V`):

```bash
curl -fsSL https://raw.githubusercontent.com/BrkBuilds/Canvas-Downloader/main/scripts/mac_first_contact.sh | bash
```

It asks for your password once at the start and then runs unattended. In order:

| | |
|---|---|
| SSH on, sleep + auto-lock off | so you can leave VNC and the machine survives the day |
| Xcode Command Line Tools | installed **headlessly** via `softwareupdate` where possible |
| Homebrew | everything below depends on it |
| **VS Code** + Claude Code, Python, Remote-SSH extensions | your IDE |
| **NoMachine** | a fast remote desktop for the few visual checks |
| **Microsoft Office** (~2 GB) | downloaded and installed for you |
| git, tmux, python@3.11, uv | the audit toolchain |

Go and do something else for half an hour.

### 2.1 When it finishes — three things, on this screen

1. **Open Word** (`Cmd+Space`, "Word") and **sign in** with Microsoft 365.
   Installing Office does not licence it. Skip this and every conversion dies
   at a licence dialog and the whole converter phase reads as broken.
2. **Full Disk Access**: System Settings → Privacy & Security → Full Disk
   Access → **+** → Terminal.
3. **Start the session on this desktop:**

   ```bash
   tmux kill-server 2>/dev/null; cd ~ && tmux new -s audit
   ```

   > **The `kill-server` is load-bearing, not tidying.** A tmux *server* is one
   > process per user socket, and `tmux new` joins the running one instead of
   > starting another. So if anything has already opened a tmux over SSH that
   > day — running the setup script, say — this command creates an Aqua-looking
   > session *inside the Background server*, inherits Background, and every
   > Keychain result is quietly false with nothing to see. The first tmux server
   > of the day must be born here.

   > This matters more than it looks. macOS gives an SSH login a *Background*
   > launchd session with **no window server**: osascript cannot drive Word,
   > Playwright cannot open a browser, TCC prompts cannot appear — each failing
   > differently and none of them saying why. A tmux **server** keeps the
   > session it was born in, so starting it here and attaching from SSH later
   > is what makes the whole day work. It is also the only way the **Keychain**
   > becomes reachable at all — see Part 4, and check it before you trust a
   > single token result.

Leave tmux running. **You are done with VNC.**

---

# PART 3 — Move to VS Code on Windows

1. VS Code → `F1` → **Remote-SSH: Connect to Host** → `<user>@<mac-ip>`
2. **File → Open Folder** → `/Users/<user>/Canvas_Downloader`
   *(it does not exist yet — that is fine, do it after 3.2)*
3. Open a terminal in VS Code (`` Ctrl+` ``). It is a shell **on the Mac**.

### 3.1 Bring the secrets over

From a Windows terminal:

```bash
scp mac_audit_secrets.env <user>@<mac-ip>:~/
```

### 3.2 Clone and build the environment

In the VS Code terminal:

```bash
tmux attach -t audit
git clone https://github.com/BrkBuilds/Canvas-Downloader.git ~/Canvas_Downloader
cd ~/Canvas_Downloader && ./scripts/mac_audit_bootstrap.sh
git checkout -b macos-audit-26        # this run's fixes go here
```

~15 min: the venv, every dependency, the pyobjc-UserNotifications pin CI uses,
Quartz, Playwright's Chromium, the settings file, the Keychain token (from your
`.env`, with a no-prompt ACL so nothing asks for a password mid-run), and
Claude Code.

**Why `tmux attach` first:** so everything you start inherits the desktop's
graphical session. VS Code's terminal is an SSH session; without attaching to
that tmux you are back in the Background session and Office automation fails.

### 3.3 Authenticate the agent

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

**The Keychain is the exception to that, and it is the trap that cost the last
run its time.** It is scoped to the security session, not the framebuffer, so a
tmux born over SSH drives the whole GUI and still cannot create an item of its
own (`errSecInteractionNotAllowed`, -25308). Every Keychain observation in the
audit is then false rather than the product: the token save "fails", auto-login
"does not restore", the 90 s watchdog looks like it is being hit.

```bash
python3 scripts/mac_aqua.py check       # session + Keychain, one line each
```

`keychain usable: True` is the gate. If it is False, the root fix is to start
tmux from a Terminal **on the desktop** (2.1 step 3) and re-attach. If you are
already mid-session and do not want to lose it, route the command instead —
Terminal.app is started by Launch Services inside Aqua and every child inherits
it, a long-lived Streamlit included:

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
# ── VNC, once: Cmd+Space -> Terminal -> paste ───────────────────────
curl -fsSL https://raw.githubusercontent.com/BrkBuilds/Canvas-Downloader/main/scripts/mac_first_contact.sh | bash
# then: sign into Word | Full Disk Access for Terminal | cd ~ && tmux new -s audit

# ── VS Code Remote-SSH from Windows, everything after ───────────────
tmux attach -t audit
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
