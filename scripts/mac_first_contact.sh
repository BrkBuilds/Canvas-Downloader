#!/usr/bin/env bash
# Set up a bare rented Mac. TWO commands, over SSH from your own PC, ~30-45 min
# mostly unattended.
#
#   curl -fsSL https://raw.githubusercontent.com/BrkBuilds/Canvas-Downloader/main/scripts/mac_first_contact.sh -o ~/fc.sh
#   bash ~/fc.sh
#
# DOWNLOAD IT, THEN RUN IT. NEVER piped into bash. Piped, the script's own text
# is on stdin and "brew install" READS stdin: it swallows the rest of the file,
# bash hits EOF and exits 0. Measured 2026-08-20 - it stopped dead at the
# toolchain step having printed no error and no [!!], so VS Code, NoMachine and
# Office never installed, and the operator then debugged a NoMachine
# "connection refused" that was really a script which had quietly ended twenty
# minutes earlier. It fails in the most misleading way available: a clean exit.
#
# HOW TO RUN IT: from Windows PowerShell (or any terminal), "ssh m1@<mac-ip>"
# using the address on the Scaleway console, then paste the two lines above.
#
# It installs, in dependency order:
#   SSH on / sleep + auto-lock off      so you can leave VNC immediately
#   Xcode Command Line Tools            git, compilers - everything needs it
#   Homebrew                            everything below is a brew cask
#   Visual Studio Code + extensions     the IDE, driven from Windows over SSH
#   NoMachine                           a fast remote desktop, if you want one
#   Microsoft Office                    ~2 GB; the converter phase needs it
#   git, tmux, python@3.11, uv          the audit's own toolchain
#
# What it CANNOT do, and nothing can: sign in to Office (licensing), grant TCC
# permissions, authenticate the agent. Those are three GUI moments at the end.
#
# Re-runnable: every step detects what is already there. You run it again on
# the second macOS install and it takes minutes.
set -uo pipefail

ok()   { printf '  \033[32m[ok]\033[0m   %s\n' "$*"; }
info() { printf '  \033[36m[..]\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33m[!!]\033[0m   %s\n' "$*"; }
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

[ "$(uname -s)" = "Darwin" ] || { echo "macOS only."; exit 1; }
USER_NAME=$(id -un)
ARCH=$(uname -m)
T0=$(date +%s)

printf '\n\033[1mCanvas Downloader - macOS audit machine setup\033[0m\n'
printf '  %s on %s, user %s\n' "$(sw_vers -productVersion)" "$ARCH" "$USER_NAME"
printf '  This takes 30-45 min. You may be asked for your password once or twice.\n'

# Ask for sudo once, up front, and keep it alive - otherwise the script stalls
# silently 20 minutes in waiting for a password nobody is watching for.
step "Administrator access"
sudo -v || { echo "sudo required."; exit 1; }
while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done 2>/dev/null &
SUDO_KEEPALIVE=$!
trap 'kill $SUDO_KEEPALIVE 2>/dev/null' EXIT
ok "granted"

# ───────────────────────────────────────── 1. escape VNC as soon as possible
step "Remote Login (SSH)"
if sudo systemsetup -getremotelogin 2>/dev/null | grep -qi "on"; then
  ok "already enabled"
else
  sudo systemsetup -setremotelogin on 2>/dev/null && ok "enabled" \
    || warn "systemsetup refused. Enable by hand:
      System Settings > General > Sharing > Remote Login = ON"
fi

step "Stay awake"
# A rented Mac that sleeps mid-run costs the run AND the hours it slept.
sudo pmset -a sleep 0 displaysleep 0 disksleep 0 2>/dev/null \
  && ok "sleep disabled" || warn "pmset failed - set Energy Saver by hand"
# A locked screen blocks the Automation prompts you have to answer.
defaults -currentHost write com.apple.screensaver idleTime -int 0 2>/dev/null || true
defaults write com.apple.screensaver askForPassword -int 0 2>/dev/null || true
ok "auto-lock disabled"

# ─────────────────────────────────────────────── 2. Xcode CLT (git, clang)
step "Xcode Command Line Tools"
if xcode-select -p >/dev/null 2>&1; then
  ok "present ($(xcode-select -p))"
else
  info "installing (this is a GUI installer - accept it if a window appears)"
  # Trick that makes `softwareupdate` list the CLT package, so it can be
  # installed headlessly instead of via the click-through dialog.
  touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
  CLT=$(softwareupdate -l 2>/dev/null \
        | grep -B1 -E 'Command Line Tools' \
        | awk -F'[*] Label: ' '/^ *\*/ {print $2}' | tail -1)
  if [ -n "$CLT" ]; then
    sudo softwareupdate -i "$CLT" --verbose && ok "installed headlessly"
  else
    xcode-select --install 2>/dev/null || true
    warn "Accept the installer window, wait for it to finish, then re-run this script."
  fi
  rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
  xcode-select -p >/dev/null 2>&1 || { warn "still missing - re-run after it finishes"; exit 1; }
fi

# ───────────────────────────────────────────────────────────── 3. Homebrew
step "Homebrew"
BREW_PREFIX="/opt/homebrew"; [ "$ARCH" = "arm64" ] || BREW_PREFIX="/usr/local"
if [ -x "$BREW_PREFIX/bin/brew" ]; then
  ok "present"
else
  info "installing..."
  NONINTERACTIVE=1 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    || { warn "Homebrew install failed"; exit 1; }
fi
eval "$("$BREW_PREFIX/bin/brew" shellenv)"
for rc in "$HOME/.zprofile" "$HOME/.bash_profile"; do
  grep -q 'brew shellenv' "$rc" 2>/dev/null || \
    echo "eval \"\$($BREW_PREFIX/bin/brew shellenv)\"" >> "$rc"
done
ok "$(brew --version | head -1)"

# ──────────────────────────────────────────────────── 4. the toolchain
step "Command line tools"
NEED=""
for t in git tmux; do command -v "$t" >/dev/null 2>&1 || NEED="$NEED $t"; done
command -v python3.11 >/dev/null 2>&1 || NEED="$NEED python@3.11"
command -v uv >/dev/null 2>&1 || NEED="$NEED uv"
if [ -n "$NEED" ]; then
  info "brew install$NEED"
  # shellcheck disable=SC2086
  brew install $NEED >/dev/null 2>&1 || brew install $NEED
fi
ok "git $(git --version | awk '{print $3}') | tmux $(tmux -V | awk '{print $2}') | python $(python3.11 -V 2>/dev/null | awk '{print $2}')"

# ──────────────────────────────────────────────────── 5. the IDE
step "Visual Studio Code"
if [ -d "/Applications/Visual Studio Code.app" ]; then
  ok "already installed"
else
  info "installing..."
  brew install --cask visual-studio-code >/dev/null 2>&1 \
    && ok "installed" || warn "cask failed - download from code.visualstudio.com"
fi
# `code` on PATH so extensions can be installed from here.
CODE_BIN="/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
if [ -x "$CODE_BIN" ]; then
  info "installing extensions..."
  for EXT in anthropic.claude-code ms-python.python ms-vscode-remote.remote-ssh; do
    "$CODE_BIN" --install-extension "$EXT" --force >/dev/null 2>&1 \
      && ok "  $EXT" || warn "  $EXT failed (install it from the Extensions pane)"
  done
fi

# ────────────────────────────────────────────── 6. a fast remote desktop
step "NoMachine (the desktop you will actually work in)"
cat <<'EOF'
      THIS IS THE WORKFLOW, not an optional extra. You run VS Code ON the Mac,
      inside the NoMachine window, with Claude Code in its terminal.

      It is also the technically better arrangement, not merely a preference:
      a VS Code launched from the Mac's own Dock is a child of the console
      session, so its terminal is in Aqua by construction. The Keychain works,
      TCC prompts appear in front of you, and none of the tmux-over-SSH
      gymnastics at the end of this script applies.

      VNC is slow to macOS structurally: Apple's Screen Sharing server speaks
      VNC, but the good compression lives in Apple's own client extensions, so
      third-party clients fall back to near-raw framebuffers. Changing VNC
      CLIENT barely helps; changing PROTOCOL does.
        NoMachine     free, NX + H.264 - what you work in, port 4000
        VNC           only to grant NoMachine its permissions, then drop it
        Parsec        DO NOT - macOS is client-only, it cannot host
EOF
if [ -d "/Applications/NoMachine.app" ]; then
  ok "already installed"
else
  brew install --cask nomachine >/dev/null 2>&1 \
    && ok "installed - grant it Screen Recording + Accessibility when asked" \
    || warn "cask failed - skip it, VS Code Remote-SSH covers most of the need"
fi

# ─────────────────────────────────────────────── 7. Microsoft Office
step "Microsoft Office"
HAVE_OFFICE=1
for a in "Microsoft Word" "Microsoft Excel" "Microsoft PowerPoint"; do
  [ -d "/Applications/$a.app" ] || HAVE_OFFICE=0
done
if [ "$HAVE_OFFICE" = "1" ]; then
  ok "Word, Excel and PowerPoint already installed"
else
  info "downloading the Office suite (~2 GB) - this is the long step"
  PKG="/tmp/office_suite.pkg"
  if curl -fL --retry 3 -o "$PKG" "https://go.microsoft.com/fwlink/?linkid=525133"; then
    if file "$PKG" | grep -qi "xar\|package"; then
      info "installing..."
      sudo installer -pkg "$PKG" -target / >/dev/null 2>&1 \
        && ok "Office installed" \
        || warn "installer failed - install from portal.office.com by hand"
    else
      warn "the download was not a package (Microsoft may have changed the link).
      Install from portal.office.com > Install Office."
    fi
    rm -f "$PKG"
  else
    warn "download failed - install from portal.office.com by hand"
  fi
fi
cat <<'EOF'
      NOTE: installing Office does NOT license it. You must open Word once and
      sign in with your Microsoft 365 account, or every conversion dies at the
      licence dialog and the whole converter phase reads as broken.
EOF

# ────────────────────────────────────────────────────────── 8. what next
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<mac-ip>")
ELAPSED=$(( ($(date +%s) - T0) / 60 ))

step "Done in ~${ELAPSED} min"
cat <<EOF

  NEXT, IN THIS ORDER. This is the whole workflow and it is the only one that
  has worked end to end. Do not improvise around it.

    1. VNC IN AND ANSWER THE PROMPTS - any VNC client, from your own PC:

           ${IP}::59010
           (TigerVNC's host::port syntax. The VNC port is on the Scaleway
            console, and TigerVNC handles Apple's ARD auth fine.)

       Click Allow on every dialog macOS raises, then grant NoMachine both of:
           Privacy & Security > Screen & System Audio Recording > + > NoMachine
           Privacy & Security > Accessibility                   > + > NoMachine
       It can neither show nor control the screen without them, and neither can
       be granted from a command line - that is the whole reason VNC is still
       in this procedure at all.

    2. START NOMACHINE:  host ${IP}   port 4000   protocol NX
       Black desktop after granting?  sudo /etc/NX/nxserver --restart
       Then drop VNC. Everything below happens in the NoMachine window.

    3. SIGN IN TO THE APPS, on that desktop:
         - Word (Cmd+Space, "Word") with Microsoft 365. Installing Office does
           NOT license it, and a licence dialog makes the whole converter phase
           read as broken.
         - VS Code, and grant it BOTH:
             Privacy & Security > Full Disk Access > + > Visual Studio Code
             Privacy & Security > Screen & System Audio Recording > + > Visual Studio Code
           Screen Recording is not optional here: TCC attributes a screenshot to
           the RESPONSIBLE process, which in this workflow is VS Code, not
           Terminal. Without it screencapture returns a bare desktop - and a
           blank capture is indistinguishable from a blank app, which is how the
           last run nearly filed a CRITICAL against a build rendering perfectly.

    4. IN VS CODE'S TERMINAL, on the Mac:

           git clone https://github.com/BrkBuilds/Canvas-Downloader.git ~/Canvas_Downloader
           cd ~/Canvas_Downloader && ./scripts/mac_audit_bootstrap.sh
           claude

  You do NOT need tmux in this workflow: VS Code is a child of the console
  session, so it is in Aqua already, and that session outlives a NoMachine
  disconnect - VS Code and anything it started keep running.

  ONLY IF YOU FALL BACK TO PLAIN SSH (VS Code Remote-SSH from Windows, or a
  bare ssh), start the long-lived session ON THE DESKTOP first:

           tmux kill-server 2>/dev/null; cd ~ && tmux new -s audit

       The kill-server is load-bearing: a tmux SERVER is one process per user
       socket and \`tmux new\` joins the running one. Start a tmux over SSH
       first and this command makes an Aqua-looking session inside the
       Background server, inherits Background, and every Keychain result is
       quietly false. The first tmux server of the day must be born here.

       This one matters more than it looks. macOS gives an SSH login a
       *Background* session with no window server: osascript cannot drive
       Word, Playwright cannot open a browser, and TCC prompts cannot appear.
       A tmux server keeps the session it was born in, so starting it HERE and
       attaching from SSH later is what makes everything work.

       The Keychain is the half you cannot probe your way around: it is scoped
       to the security session, so a tmux born over SSH drives the whole GUI
       and still cannot create an item of its own - and then every Keychain
       observation in the audit is false rather than the product. Gate on
       "python3 scripts/mac_aqua.py check" saying "keychain usable: True",
       never on "launchctl managername", which reports Background even here.

  Then, from ${USER_NAME}@${IP}, attach to it before running anything at all.
  A command started outside that tmux is in the Background session and fails at
  the Keychain, at Office automation and at every screenshot - each differently,
  and none of them saying why:

       tmux attach -t audit
       git clone https://github.com/BrkBuilds/Canvas-Downloader.git ~/Canvas_Downloader
       cd ~/Canvas_Downloader && ./scripts/mac_audit_bootstrap.sh

  You can see the Mac's screen at any time without a remote desktop:

       ssh ${USER_NAME}@${IP} 'screencapture -x /tmp/s.png'
       scp ${USER_NAME}@${IP}:/tmp/s.png .

EOF
