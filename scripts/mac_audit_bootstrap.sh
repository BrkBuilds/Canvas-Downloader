#!/usr/bin/env bash
# Bare macOS -> ready to run a live audit, in one command.
#
#   curl -fsSL https://raw.githubusercontent.com/birkls/Canvas_LMS_batch_file_downloader/main/scripts/mac_audit_bootstrap.sh | bash
# or, once the repo is cloned:
#   ./scripts/mac_audit_bootstrap.sh
#
# Written to be run TWICE - once per macOS install (15, then 26). Every step is
# idempotent and skips instantly if already done, so the second run is minutes,
# not an hour. The only things it cannot do for you are the GUI grants at the
# end; it prints them as an explicit checklist rather than assuming.
#
# Secrets never live in this file. Put them in ~/mac_audit_secrets.env before
# running (scp it over, or paste it once) and this script wires them in:
#
#   CANVAS_URL=https://<your>.instructure.com
#   CANVAS_TOKEN=<canvas access token>
#
set -uo pipefail

REPO_URL="https://github.com/birkls/Canvas_LMS_batch_file_downloader.git"
REPO_DIR="${REPO_DIR:-$HOME/Canvas_Downloader}"
SECRETS="${SECRETS:-$HOME/mac_audit_secrets.env}"
PYVER="3.11"
BRANCH="${BRANCH:-main}"

STEP=0
ok()   { printf '  \033[32m[ok]\033[0m   %s\n' "$*"; }
info() { printf '  \033[36m[..]\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33m[!!]\033[0m   %s\n' "$*"; }
die()  { printf '  \033[31m[XX]\033[0m   %s\n' "$*"; exit 1; }
step() { STEP=$((STEP+1)); printf '\n\033[1m== %d. %s\033[0m\n' "$STEP" "$*"; }

t0=$(date +%s)

# ─────────────────────────────────────────────────────────── 1. platform
step "Platform"
[ "$(uname -s)" = "Darwin" ] || die "This is a macOS bootstrap; uname says $(uname -s)."
ARCH=$(uname -m)
OSVER=$(sw_vers -productVersion)
ok "macOS $OSVER on $ARCH"
[ "$ARCH" = "arm64" ] || warn "Not arm64 - the shipped build is Apple silicon."
if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = "1" ]; then
  die "This shell is running under Rosetta. Open a native arm64 Terminal."
fi
case "${OSVER%%.*}" in
  13|14) warn "macOS ${OSVER%%.*}: fda_nudge_applies() is hard-gated to 15+, so the Full Disk Access nudge CANNOT be tested here." ;;
  *)     ok "macOS 15+ - the FDA nudge and is_macos_15_plus() paths are reachable" ;;
esac

# ──────────────────────────────────────────── 2. Xcode command line tools
step "Xcode command line tools"
if xcode-select -p >/dev/null 2>&1; then
  ok "already installed ($(xcode-select -p))"
else
  warn "Not installed. Triggering the GUI installer - accept it, wait, then re-run this script."
  xcode-select --install || true
  die "Re-run after the Command Line Tools finish installing."
fi

# ──────────────────────────────────────────────────────────── 3. Homebrew
step "Homebrew"
BREW_PREFIX="/opt/homebrew"
[ "$ARCH" = "arm64" ] || BREW_PREFIX="/usr/local"
if [ -x "$BREW_PREFIX/bin/brew" ]; then
  ok "present at $BREW_PREFIX"
else
  info "installing (non-interactive)..."
  NONINTERACTIVE=1 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    || die "Homebrew install failed."
fi
eval "$("$BREW_PREFIX/bin/brew" shellenv)"
# Persist for future shells (and for tmux panes started later).
for rc in "$HOME/.zprofile" "$HOME/.bash_profile"; do
  grep -q 'brew shellenv' "$rc" 2>/dev/null || \
    echo "eval \"\$($BREW_PREFIX/bin/brew shellenv)\"" >> "$rc"
done
ok "brew $(brew --version | head -1)"

# ─────────────────────────────────────────────────────── 4. system tools
step "System tools"
NEED=""
for t in git tmux; do command -v "$t" >/dev/null 2>&1 || NEED="$NEED $t"; done
command -v "python$PYVER" >/dev/null 2>&1 || NEED="$NEED python@$PYVER"
command -v uv >/dev/null 2>&1 || NEED="$NEED uv"
if [ -n "$NEED" ]; then
  info "brew install$NEED"
  # shellcheck disable=SC2086
  brew install $NEED || die "brew install failed for:$NEED"
fi
command -v "python$PYVER" >/dev/null 2>&1 || die "python$PYVER still not on PATH."
ok "git $(git --version | awk '{print $3}') | tmux $(tmux -V | awk '{print $2}') | python $("python$PYVER" -V | awk '{print $2}') | uv $(uv --version 2>/dev/null | awk '{print $2}')"

# ───────────────────────────────────────────────────────────── 5. repo
step "Repository"
if [ -d "$REPO_DIR/.git" ]; then
  info "pulling $BRANCH..."
  git -C "$REPO_DIR" fetch --quiet origin "$BRANCH" && \
  git -C "$REPO_DIR" checkout --quiet "$BRANCH" && \
  git -C "$REPO_DIR" pull --quiet --ff-only origin "$BRANCH" || \
    warn "Pull failed - working tree may be dirty. Continuing with what is on disk."
else
  info "cloning into $REPO_DIR ..."
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$REPO_DIR" || die "Clone failed."
fi
cd "$REPO_DIR" || die "Cannot cd to $REPO_DIR"
ok "$REPO_DIR @ $(git rev-parse --short HEAD) ($(git log -1 --format=%s | cut -c1-58))"

# ──────────────────────────────────────────── 6. virtualenv + dependencies
step "Python environment"
if [ ! -d .venv ]; then
  info "creating .venv on python$PYVER"
  "python$PYVER" -m venv .venv || die "venv creation failed."
fi
# shellcheck disable=SC1091
source .venv/bin/activate
PY=.venv/bin/python

# uv resolves and installs this requirements set in well under a minute where
# pip takes several. Fall back silently if uv is unavailable.
if command -v uv >/dev/null 2>&1; then
  INSTALL="uv pip install --python $PY"
else
  INSTALL="$PY -m pip install"
  $PY -m pip install --quiet --upgrade pip
fi

if $PY -c "import streamlit, canvasapi, playwright, faster_whisper" >/dev/null 2>&1; then
  ok "dependencies already present"
else
  info "installing requirements.txt ..."
  $INSTALL -r requirements.txt || die "Dependency install failed."
fi
$PY -c "import pytest" >/dev/null 2>&1 || $INSTALL pytest >/dev/null 2>&1 || true
$PY -c "import playwright" >/dev/null 2>&1 || $INSTALL playwright || die "playwright install failed."

# pyobjc-framework-* packages must all share ONE version, and the pywebview
# line can bump pyobjc-core underneath them. Pin UserNotifications to whatever
# core finally resolved to, exactly as .github/workflows/build-macos.yml does -
# otherwise the app silently degrades to the deprecated NSUserNotification path
# and the modern notification code is never the thing under test.
if ! $PY -c "import UserNotifications" >/dev/null 2>&1; then
  PYOBJC_VER=$($PY -c 'import objc; print(objc.__version__)' 2>/dev/null || echo "")
  if [ -n "$PYOBJC_VER" ]; then
    info "pinning pyobjc-framework-UserNotifications==$PYOBJC_VER"
    $INSTALL "pyobjc-framework-UserNotifications==$PYOBJC_VER" || \
      warn "Could not pin UserNotifications - notifications will use the deprecated path."
  fi
fi
$PY -c "import UserNotifications" >/dev/null 2>&1 && ok "UserNotifications binding OK" \
  || warn "UserNotifications binding missing (deprecated notification path will be used)"

# ────────────────────────────────────────────────── 7. Playwright browser
step "Playwright Chromium"
if $PY -c "
from playwright.sync_api import sync_playwright
from pathlib import Path
import sys
with sync_playwright() as p:
    sys.exit(0 if Path(p.chromium.executable_path).exists() else 1)
" >/dev/null 2>&1; then
  ok "already installed"
else
  info "downloading chromium ..."
  $PY -m playwright install chromium || die "playwright install chromium failed."
fi

# ──────────────────────────────────────────────────── 8. credentials
step "Credentials"
if [ -f "$SECRETS" ]; then
  # shellcheck disable=SC1090
  set -a; source "$SECRETS"; set +a
  ok "loaded $SECRETS"
else
  warn "No $SECRETS - the audit will stop at the login wall."
  cat <<EOF

      Create it (on your own machine, then scp it over) with:

        CANVAS_URL=https://<your>.instructure.com
        CANVAS_TOKEN=<canvas access token>

      then re-run this script. It is the difference between an unattended
      audit and one that needs you to type a token into every run.

EOF
fi

if [ -n "${CANVAS_URL:-}" ]; then
  # The audit seeds its isolated config from this file (SEEDED_FROM_REAL), and
  # reads the TOKEN from the login Keychain - which is NOT isolated, so one
  # write here serves every run.
  if [ ! -f canvas_downloader_settings.json ]; then
    cat > canvas_downloader_settings.json <<EOF
{
    "api_url": "$CANVAS_URL",
    "debug_mode": true,
    "error_log_enabled": true,
    "notifications_enabled": true,
    "show_help_text": true,
    "panopto_globally_enabled": true
}
EOF
    ok "seeded canvas_downloader_settings.json"
  else
    ok "canvas_downloader_settings.json already present"
  fi

  if [ -n "${CANVAS_TOKEN:-}" ]; then
    if security find-generic-password -s CanvasDownloader -a "$CANVAS_URL" -w >/dev/null 2>&1; then
      ok "Canvas token already in the login Keychain"
    else
      security add-generic-password -U -s CanvasDownloader -a "$CANVAS_URL" \
        -w "$CANVAS_TOKEN" -T /usr/bin/security -T "" 2>/dev/null \
        && ok "Canvas token written to the login Keychain" \
        || warn "Could not write the Keychain item - log in once through the app UI instead."
    fi
  fi
fi

# ─────────────────────────────────────────────────────── 9. the agent
step "Claude Code"
if command -v claude >/dev/null 2>&1; then
  ok "already installed ($(claude --version 2>/dev/null | head -1))"
else
  info "installing ..."
  curl -fsSL https://claude.ai/install.sh | bash >/dev/null 2>&1 \
    || (command -v npm >/dev/null 2>&1 && npm install -g @anthropic-ai/claude-code >/dev/null 2>&1) \
    || warn "Automatic install failed - see https://docs.claude.com/claude-code for the current installer."
  command -v claude >/dev/null 2>&1 && ok "installed" || warn "claude not on PATH yet (open a new shell)"
fi

# ──────────────────────────────────────────────────────── 10. preflight
step "Preflight"
$PY scripts/mac_audit_doctor.py || true

elapsed=$(( $(date +%s) - t0 ))
cat <<EOF

════════════════════════════════════════════════════════════════════════
  Bootstrap finished in ${elapsed}s.

  STILL MANUAL - these need the graphical session and cannot be scripted:

   1. Sign in to Microsoft Office once (open Word, sign in with your M365
      account). Without it every Office conversion fails at the licence
      dialog and the whole converter phase reads as broken.

   2. Grant Full Disk Access to Terminal.app:
        System Settings > Privacy & Security > Full Disk Access > +
      Do this AFTER you have deliberately seen the app's macOS-15 FDA nudge
      once - that nudge is itself under test.

   3. Authenticate the agent:  claude
      (one browser sign-in; it persists for this OS install)

   4. START TMUX FROM THE DESKTOP, NOT FROM SSH:
        open Terminal.app on the Mac's own screen, then:
        cd $REPO_DIR && tmux new -s audit
      Everything the agent spawns inherits that GUI (Aqua) session, which is
      what lets osascript drive Word and Playwright open a real window.
      From then on you can work over SSH with:  tmux attach -t audit

   5. Re-run the preflight until it says READY:
        $REPO_DIR/.venv/bin/python scripts/mac_audit_doctor.py

  Then hand the agent tests/audit/MAC_AUDIT_PROMPT.md and let it work.
════════════════════════════════════════════════════════════════════════
EOF
