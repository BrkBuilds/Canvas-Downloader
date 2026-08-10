#!/usr/bin/env bash
# The ONLY thing you type in the slow VNC session.
#
# Scaleway hands you a VNC console. That console is painful over a WAN (5+ s per
# mouse move is normal, and it is the protocol's fault, not your connection).
# So do not work in it - use it for ~2 minutes to run this, then never again.
#
#   curl -fsSL https://raw.githubusercontent.com/birkls/Canvas_LMS_batch_file_downloader/main/scripts/mac_first_contact.sh | bash
#
# ...or just type the four commands it prints at the end; nothing here is magic.
#
# It turns on SSH, stops the machine sleeping or locking mid-audit, drops the
# resolution (which helps EVERY remote protocol far more than changing client),
# optionally installs a fast remote desktop, and tells you exactly how to
# connect. After this, everything else happens over SSH.
set -uo pipefail

ok()   { printf '  \033[32m[ok]\033[0m   %s\n' "$*"; }
info() { printf '  \033[36m[..]\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33m[!!]\033[0m   %s\n' "$*"; }
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

[ "$(uname -s)" = "Darwin" ] || { echo "macOS only."; exit 1; }
USER_NAME=$(id -un)

# ─────────────────────────────────────────────────────────────── 1. SSH
step "Remote Login (SSH)"
if sudo systemsetup -getremotelogin 2>/dev/null | grep -qi "on"; then
  ok "already enabled"
else
  info "enabling..."
  sudo systemsetup -setremotelogin on 2>/dev/null \
    && ok "enabled" \
    || warn "systemsetup refused (it often needs Full Disk Access for Terminal).
      Do it by hand: System Settings > General > Sharing > Remote Login = ON"
fi

# ────────────────────────────────────────────── 2. never sleep, never lock
step "Stay awake"
# A rented Mac that sleeps mid-run costs you the run AND the hours it slept.
sudo pmset -a sleep 0 displaysleep 0 disksleep 0 womp 1 2>/dev/null \
  && ok "sleep disabled (system, display, disk)" \
  || warn "pmset failed - set Energy Saver by hand"

# A locked screen does not kill the window server, but it does block the
# Automation prompts you need to answer and any UI scripting.
defaults write com.apple.screensaver idleTime -int 0 2>/dev/null || true
sudo defaults write /Library/Preferences/com.apple.screensaver loginWindowIdleTime -int 0 2>/dev/null || true
defaults -currentHost write com.apple.screensaver idleTime -int 0 2>/dev/null || true
ok "screen saver / auto-lock disabled"

# ──────────────────────────────────────────────────────── 3. resolution
step "Display"
CUR=$(system_profiler SPDisplaysDataType 2>/dev/null | grep -i "Resolution" | head -1 | sed 's/^ *//')
info "${CUR:-resolution unknown}"
cat <<'EOF'
      A headless Mac renders at whatever its virtual display reports, and every
      remote protocol pays for those pixels on every frame. Dropping to
      1440x900 is the single biggest responsiveness win available - bigger than
      changing client. Set it in System Settings > Displays while you are here.
EOF

# ─────────────────────────────────────────── 4. a faster remote desktop
step "Remote desktop"
cat <<'EOF'
      VNC is slow to macOS for a structural reason: Apple's Screen Sharing
      server speaks VNC, but the good compression is in Apple's own client
      extensions, so third-party clients fall back to sending near-raw
      framebuffers. Changing VNC client barely helps. Changing PROTOCOL does.

        NoMachine        free, NX + H.264, by far the best free option
        Chrome Remote    free, H.264, tunnels out so no firewall work at all
        Parsec           DO NOT - macOS is client-only, it cannot host

      NoMachine also needs Screen Recording + Accessibility in
      System Settings > Privacy & Security before it will show you anything.
EOF
if command -v brew >/dev/null 2>&1; then
  read -r -t 20 -p "  Install NoMachine now with brew? [y/N] " ans || ans=""
  case "${ans:-N}" in
    [yY]*) brew install --cask nomachine && ok "NoMachine installed" ;;
    *)     info "skipped" ;;
  esac
else
  info "Homebrew not installed yet - mac_audit_bootstrap.sh installs it."
fi

# ─────────────────────────────────────────────────────────── 5. how to connect
step "You are done with VNC"
IP=$(ipconfig getifaddr en0 2>/dev/null || echo "<mac-ip>")
cat <<EOF

  From Windows, everything from here is SSH:

      ssh ${USER_NAME}@${IP}

  Then:

      git clone -b macos-audit-v2.0.2 \\
        https://github.com/birkls/Canvas_LMS_batch_file_downloader.git ~/Canvas_Downloader
      cd ~/Canvas_Downloader && ./scripts/mac_audit_bootstrap.sh

  BUT: start the long-lived session from the DESKTOP, not from SSH.
  In this VNC window, before you leave it:

      cd ~ && tmux new -s audit

  Everything the agent spawns then inherits the graphical (Aqua) session,
  which is what lets osascript drive Word and lets TCC prompts appear.
  From SSH you just: tmux attach -t audit

  You can SEE the desktop without any remote-desktop protocol at all:

      ssh ${USER_NAME}@${IP} 'screencapture -x /tmp/s.png' && scp ${USER_NAME}@${IP}:/tmp/s.png .

  The agent does exactly that for itself - it reads the PNG. So you do not
  need to watch, and it does not need you to describe what is on screen.

EOF
