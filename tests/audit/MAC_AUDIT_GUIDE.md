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

> **Commit `308e734` contains a corrupted `panopto/shortcut.py`** — a commit
> landed while a mutation pass had it swapped out, so `kind_extensions()` was
> committed returning only the native suffix. Cross-platform `.url`/`.webloc`
> adoption is broken in that commit, in the exact subsystem this audit is for.
> Your working tree has the fix; HEAD does not.

```bash
cd "G:/18 AI/ANTIGRAVITY WORKSPACES/Canvas Downloader"
python -m pytest tests/ -q                 # ~3218 passed, 0 failed
git checkout -b macos-audit-v2.0.2
git add -A && git commit -m "macOS audit tooling for v2.0.2"
git push -u origin macos-audit-v2.0.2
```

### 0.2 On your Windows PC

- **VS Code** with the **Remote - SSH** extension. This is your IDE for the
  whole day — install it now, not on the Mac.
- Your `mac_audit_secrets.env` (you have this).
- Microsoft 365 credentials to hand.

---

# PART 1 — Rent

Scaleway → Apple silicon → **Mac mini M-series** → **macOS 15 Sequoia** →
**closest region**.

*Why 15:* `fda_nudge_applies()` is hard-gated to macOS 15+, so the Full Disk
Access nudge and every `is_macos_15_plus()` path cannot render below it. Your
build is made on macOS 14, so running on 15 is also the real user path.

Note the VNC address/password and the SSH user/IP.

---

# PART 2 — The one command (VNC, ~40 min)

Connect with Scaleway's VNC console. It will be slow. You are here once.

**Open a terminal:** press `Cmd+Space`, type `Terminal`, press `Return`.

**Paste this and press Return** (paste is `Cmd+V`):

```bash
curl -fsSL https://raw.githubusercontent.com/birkls/Canvas_LMS_batch_file_downloader/main/scripts/mac_first_contact.sh | bash
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
   cd ~ && tmux new -s audit
   ```

   > This matters more than it looks. macOS gives an SSH login a *Background*
   > launchd session with **no window server**: osascript cannot drive Word,
   > Playwright cannot open a browser, TCC prompts cannot appear — each failing
   > differently and none of them saying why. A tmux **server** keeps the
   > session it was born in, so starting it here and attaching from SSH later
   > is what makes the whole day work.

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
git clone -b macos-audit-v2.0.2 \
  https://github.com/birkls/Canvas_LMS_batch_file_downloader.git ~/Canvas_Downloader
cd ~/Canvas_Downloader && ./scripts/mac_audit_bootstrap.sh
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

python scripts/mac_audit_doctor.py       # until it prints READY
python scripts/mac_smoke.py --with-hfs   # ~2 min
```

The doctor probes window-server access directly (screencapture, System Events,
launching a GUI app). Do **not** gate on `launchctl managername == "Aqua"` -
it reports `Background` on a Scaleway Mac even when everything works.

Then prove the harness works before trusting any result from it:

```bash
python -m tests.audit run new --label macos-15-v2.0.2
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
git add -A && git commit -m "macOS 15 audit fixes" && git push
```

**The Mac is rented. Nothing on it survives.** Push early and often.

---

# PART 6 — macOS 26

Reinstall from the Scaleway console, repeat **Parts 2 → 5**. Much faster:
every script detects what already exists, and `mac_audit_secrets.env` re-seeds
the Keychain with no typing. The genuinely manual repeats are the same three:
Office sign-in, TCC grants, tmux from the desktop.

Expect differences to cluster in **TCC behaviour**, **notification delivery**
and **WKWebView rendering**. Anything that worked on 15 and misbehaves on 26 is
the most valuable thing this second install can produce.

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
curl -fsSL https://raw.githubusercontent.com/birkls/Canvas_LMS_batch_file_downloader/main/scripts/mac_first_contact.sh | bash
# then: sign into Word | Full Disk Access for Terminal | cd ~ && tmux new -s audit

# ── VS Code Remote-SSH from Windows, everything after ───────────────
tmux attach -t audit
git clone -b macos-audit-v2.0.2 https://github.com/birkls/Canvas_LMS_batch_file_downloader.git ~/Canvas_Downloader
cd ~/Canvas_Downloader && ./scripts/mac_audit_bootstrap.sh

source .venv/bin/activate
python scripts/mac_audit_doctor.py         # READY
python scripts/mac_smoke.py --with-hfs

python -m tests.audit run new --label macos-15-v2.0.2
python -m tests.audit app start
python -m tests.audit browser open
python -m tests.audit canvas snapshot 43660
python -m tests.audit flow download smoke --courses 43667

claude          # paste tests/audit/MAC_AUDIT_PROMPT.md
```
