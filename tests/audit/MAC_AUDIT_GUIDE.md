# Renting a Mac and running the audit — the practical guide

For the human. The agent's instructions are `MAC_AUDIT_PROMPT.md`; the audit
plan is `MAC_RUNBOOK.md`. This file is only about *getting there fast* and
*not paying for the same setup twice*.

---

## The idea that changes everything

**Put the agent on the Mac, not on your PC.**

Last time the agent ran on Windows and drove the Mac by proxy, so every log,
screenshot and debug artifact had to be carried across by hand. That is the
time sink, and it disappears entirely if the agent runs *on the Mac over SSH*:
it reads the debug log, the manifest, the disk, the Canvas API and its own
screenshots directly.

Which means **you barely need the remote desktop at all**. The GUI is required
for four things only:

| Needs the desktop | Roughly |
|---|---|
| Initial login + install a decent remote client + enable SSH | 10 min |
| Microsoft 365 sign-in | 5 min |
| TCC grants (Automation, Full Disk Access) + `claude` auth | 10 min |
| Watching the packaged `.app` render (phase M3) — WKWebView, splash, Dock | 30-45 min |

Everything else is SSH.

### The one rule you must not get wrong

macOS gives an SSH login a **Background** launchd session with no window
server. In it, `osascript` cannot drive Word, Playwright cannot open a browser,
and TCC prompts cannot appear — each failing differently and none of them
saying why.

> **Start `tmux` from a Terminal on the Mac's own desktop. Attach to it from
> SSH.** The tmux server keeps the graphical (Aqua) session it was born in, and
> every pane inherits it.

`scripts/mac_audit_doctor.py` refuses to pass until `launchctl managername`
prints `Aqua`.

---

## The setup, in the order that costs least

The whole trick is: **spend ~3 minutes in Scaleway's VNC console, then never
open it again.** Everything after that is SSH.

| # | Where | What | Time |
|---|---|---|---|
| 1 | Scaleway console | Create the instance (macOS 15, closest region). Note the VNC + SSH details. | 5 min |
| 2 | **VNC** | Run `mac_first_contact.sh`. Turns on SSH, disables sleep AND auto-lock, tells you how to connect. | 2 min |
| 3 | **VNC** | System Settings → Displays → **1440×900**. Biggest responsiveness win there is. | 1 min |
| 4 | **VNC** | `cd ~ && tmux new -s audit` — **this session must be born on the desktop.** | 10 s |
| 5 | SSH | `tmux attach -t audit`, clone, run `mac_audit_bootstrap.sh`. Unattended. | 15-25 min |
| 6 | **VNC** *(while 5 runs)* | Sign in to Office. Authenticate `claude`. | 10 min |
| 7 | SSH | `mac_audit_doctor.py` until READY, then `mac_smoke.py --with-hfs`. | 5 min |
| 8 | SSH | Hand the agent `MAC_AUDIT_PROMPT.md`. | — |
| 9 | **VNC** *(on demand)* | Answer TCC/Automation prompts when the agent says which button. | 5 min |

Steps 5 and 6 overlap — start the bootstrap, then do the Office/agent logins
while it downloads.

```bash
curl -fsSL https://raw.githubusercontent.com/birkls/Canvas_LMS_batch_file_downloader/main/scripts/mac_first_contact.sh | bash
```

### You do not have to watch — the agent can see the screen

`screencapture` writes the real desktop to a PNG from a plain shell, so the
agent reads the window server's output directly. `scripts/mac_eyes.py` wraps it:

```bash
python scripts/mac_eyes.py shot --window "Canvas Downloader"
python scripts/mac_eyes.py watch --seconds 20      # transients: banners, splash
python scripts/mac_eyes.py dialogs                 # is anything awaiting a human?
python scripts/mac_eyes.py dock                    # flags tiles whose target is gone
python scripts/mac_eyes.py windows
```

That is what removes the shuttling: the agent confirms a notification banner
appeared, compares the WKWebView render against its own Chrome screenshots, and
checks for a stale Dock tile **by itself**.

**The one thing it cannot do**: macOS refuses synthetic clicks on TCC consent
prompts by design. So `dialogs` tells you a prompt is up and which button it
wants — a person still has to press it. That is a handful of clicks, not a day
of relaying.

For your own eyes: `ssh mac 'screencapture -x /tmp/s.png' && scp mac:/tmp/s.png .`

## Remote desktop: replace TigerVNC

TigerVNC is slow here for a structural reason, not because your connection is
bad. Apple's Screen Sharing server *is* VNC, but Apple's own client negotiates
a proprietary compression extension. Third-party clients fall back to
Raw/ZRLE — a full framebuffer per update — so a 5-second lag per mouse move is
exactly what you would expect over a WAN.

**Recommended: NoMachine** (free). NX protocol with H.264 video encoding; on a
WAN it is typically an order of magnitude more responsive than VNC.

1. Connect once with Scaleway's VNC (you only need it this once).
2. **Drop the resolution first** — System Settings → Displays → 1440×900.
   This alone roughly halves the pixels and helps every protocol.
3. Download NoMachine for Mac, install, and grant it **Screen Recording** and
   **Accessibility** in System Settings → Privacy & Security.
4. Connect from Windows with the NoMachine client. Close VNC for good.

**Alternative: Chrome Remote Desktop** — zero firewall/port work (it tunnels
out), browser-based, needs a Google account, also H.264. Slightly less
tunable than NoMachine but the easiest thing that works.

**Also enable SSH immediately**: System Settings → General → Sharing → **Remote
Login** on. That is your real workspace.

**Optional, 5 minutes, worth it: Tailscale** on both machines. Gives the Mac a
stable private IP so SSH and NoMachine do not care about Scaleway's networking
or your IP changing.

---

## Tonight (before you rent anything)

1. **Commit and push — this one is not optional.** The Mac clones from
   `github.com/birkls/Canvas_LMS_batch_file_downloader`, so whatever is in the
   pushed branch is what gets audited.

   > **Commit `308e734` contains a corrupted `panopto/shortcut.py`.** A commit
   > landed while a mutation pass had that file swapped out, so
   > `kind_extensions()` was committed returning only the native suffix —
   > cross-platform shortcut adoption silently broken, in the exact subsystem
   > this audit is for. **The working tree has the fix; HEAD does not.** Clone
   > that commit onto the Mac and three `tests/test_panopto_shortcut.py` tests
   > fail immediately and Panopto `.webloc`/`.url` adoption misbehaves all day.
   >
   > The same commit also captured `_macos_branch_probe_tmp.py`, a test's
   > temp file. It is deleted on disk; `git add -A` records the deletion.

   ```bash
   git checkout -b macos-audit-v2.0.2
   git add -A && git commit -m "..." && git push -u origin macos-audit-v2.0.2
   # then confirm the tree you are about to audit is actually green:
   python -m pytest tests/ -q
   ```
   ```bash
   git checkout -b macos-audit-v2.0.2
   git add -A && git commit -m "..." && git push -u origin macos-audit-v2.0.2
   ```
   You clone that branch on the Mac (step below) and the bootstrap stays on
   whatever branch it finds — it will not drag you back to `main`.

2. **Write `mac_audit_secrets.env`** and keep it somewhere you can paste or
   `scp` from. This is what makes the *second* install cheap:
   ```
   CANVAS_URL=https://<your>.instructure.com
   CANVAS_TOKEN=<canvas access token>
   ```
   The bootstrap writes the token straight into the login Keychain with
   `security add-generic-password`, so the app is signed in before it ever
   starts and no run stops at the login wall.

3. **Check the token still works** and is not about to expire — mint a fresh
   one if in doubt. A dead token wastes the first hour of rented time.

4. **Have your M365 credentials to hand.** Office is required for the
   highest-risk phase.

5. **Pick the closest Scaleway region** (latency is the whole game for the GUI
   part) and check the billing granularity — Apple silicon instances are
   commonly billed with a **24-hour minimum**, which is what makes "install 15,
   audit, reinstall to 26, audit" affordable in one rental. Confirm before you
   plan on it.

---

## Tomorrow — install #1 (macOS 15 Sequoia)

Chosen because `fda_nudge_applies()` is hard-gated to 15+: the Full Disk Access
nudge and every `is_macos_15_plus()` path **cannot render below 15**. Your
build is made on macOS 14, so running it on 15 also tests the real user path —
built on 14, run on 15.

```bash
# 1. connect via Scaleway VNC, drop resolution, install NoMachine, enable SSH
# 2. then, in Terminal ON THE DESKTOP:
git clone -b macos-audit-v2.0.2 \
  https://github.com/birkls/Canvas_LMS_batch_file_downloader.git ~/Canvas_Downloader
cd ~/Canvas_Downloader && ./scripts/mac_audit_bootstrap.sh
```

(Clone first rather than `curl | bash`: the script lives *in* the repo, so
fetching it by raw URL means hard-coding a branch name in two places and
getting the wrong one if you rename. Cloning first has neither problem — the
script sees an existing checkout and just pulls. If `git` is not yet present,
macOS offers the Command Line Tools installer at this point; accept it.)

The script is idempotent and prints exactly what is left. It handles: Xcode CLT,
Homebrew, Python 3.11, `uv`, the venv and all dependencies, the
pyobjc-UserNotifications version pin (the same one CI does), Playwright's
Chromium, tmux, the settings file, the Keychain token, and Claude Code.

Then the four manual things it cannot do:

1. Open Word once and sign in to M365.
2. `claude` → authenticate.
3. **See the app's macOS-15 FDA nudge once deliberately** (it is under test),
   *then* grant Full Disk Access to Terminal.app.
4. Start the session **on the desktop**:
   ```bash
   cd ~/Canvas_Downloader && tmux new -s audit
   ```

Now move to SSH from Windows:

```bash
ssh <user>@<mac>
tmux attach -t audit
source .venv/bin/activate
python scripts/mac_audit_doctor.py        # until it says READY
claude
```

Paste `tests/audit/MAC_AUDIT_PROMPT.md` into the agent and let it work.

### While it runs

- You do not need to watch. Check in via `tmux attach`.
- Be available for GUI moments: the first-run **Automation prompts** (grant all
  three Office apps) and anything the agent explicitly asks you to look at.
- Phase M3 (the packaged `.app`) is the one part where your eyes help — that is
  when NoMachine earns its keep, because the harness drives Chrome and the
  shipped app renders in **WKWebView**.

### Before you reinstall

```bash
git add -A && git commit -m "macOS 15 audit fixes" && git push
```

**The Mac is rented. Nothing on it survives.** Push early and often.

---

## Tomorrow — install #2 (macOS 26 Tahoe)

Same sequence. It should be minutes, not an hour:

- `boot.sh` skips everything already done and reinstalls the rest unattended.
- `mac_audit_secrets.env` re-seeds the Keychain and settings with no typing.
- The only genuinely manual repeats are M365 sign-in, `claude` auth, TCC grants
  and starting tmux from the desktop.

Expect the differences from 15 to cluster in exactly three places: **TCC
wording and prompt behaviour**, **notification delivery**, and **WKWebView
rendering**. Run the same phases; anything that behaved on 15 and misbehaves on
26 is a genuine forward-compatibility finding and the most valuable thing this
second install can produce.

---

## What "done" looks like

- `python -m tests.audit report build` on both installs.
- Every finding names its oracle pair, and says whether it was fixed.
- An explicit list of **what was not reached**. That list is the honest output
  of an audit and it is what tells you whether v2.0.2 is safe to ship.
