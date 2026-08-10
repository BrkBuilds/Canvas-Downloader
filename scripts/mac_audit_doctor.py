#!/usr/bin/env python3
"""Preflight for a macOS live audit: is this machine actually ready?

Run it after ``scripts/mac_audit_bootstrap.sh`` and again any time something
behaves oddly. It answers one question per line and exits non-zero if anything
BLOCKING is wrong, so an agent can gate on it:

    python3 scripts/mac_audit_doctor.py            # human table + fixes
    python3 scripts/mac_audit_doctor.py --json     # machine-readable
    python3 scripts/mac_audit_doctor.py --quick    # skip network/Office probes

Three severities:
  BLOCK  - the audit cannot produce trustworthy results until this is fixed
  WARN   - a phase will be skipped or degraded; note it in the findings
  INFO   - recorded so the run can be interpreted later

THE ONE THAT CATCHES PEOPLE OUT is `gui_session`. macOS gives an SSH login a
*Background* launchd session with no window server, so osascript cannot drive
Word, Playwright cannot open a headed browser, and TCC prompts cannot appear -
each failing in a different, confusing way. Start tmux from a Terminal INSIDE
the graphical session and attach to it over SSH; the tmux server keeps the Aqua
session it was born in, and every pane inherits it.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

BLOCK, WARN, INFO = "BLOCK", "WARN", "INFO"
results: list[dict] = []


def add(name, ok, severity, detail="", fix=""):
    results.append({"check": name, "ok": bool(ok),
                    "severity": severity if not ok else INFO,
                    "detail": str(detail), "fix": fix})
    return ok


def sh(cmd, timeout=20):
    """Run *cmd*, return (rc, stdout+stderr). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as e:                                   # noqa: BLE001
        return 127, f"{type(e).__name__}: {e}"


# ───────────────────────────────────────────────────────────── platform

def check_platform():
    add("macOS", sys.platform == "darwin", BLOCK, sys.platform,
        "This script only means anything on macOS.")
    if sys.platform != "darwin":
        return
    ver = platform.mac_ver()[0] or "?"
    major = int(ver.split(".")[0]) if ver[0].isdigit() else 0
    add("macOS version", major >= 13, WARN, ver,
        "13 (Ventura) is the app's floor.")
    # 15+ is where fda_nudge_applies() and is_macos_15_plus() become reachable.
    results.append({
        "check": "macOS 15+ paths reachable", "ok": True, "severity": INFO,
        "detail": ("YES - the Full Disk Access nudge and is_macos_15_plus() "
                   "can render" if major >= 15 else
                   "NO - fda_nudge_applies() returns False below 15, so that "
                   "UI cannot be tested on this OS"),
        "fix": ""})

    arch = platform.machine()
    add("Apple silicon", arch == "arm64", WARN, arch,
        "The shipped build is arm64; an x86_64 host tests a different binary.")

    rc, out = sh(["sysctl", "-n", "sysctl.proc_translated"])
    translated = out.strip() == "1"
    add("not under Rosetta", not translated, BLOCK,
        "translated" if translated else "native",
        "Run an arm64 terminal. Native wheels (ctranslate2, pyobjc) are "
        "pinned per arch and fail in ways that look like nothing else.")


# ─────────────────────────────────────────────── the GUI (Aqua) session

def check_gui_session():
    """Can this process actually reach the window server? Test it, don't infer.

    This check originally gated on ``launchctl managername == "Aqua"`` and that
    was WRONG - measured on a Scaleway Apple-silicon Mac 2026-08-10, where it
    reports **Background** from SSH *and from Terminal.app on the desktop*,
    while `screencapture` writes a 4.4 MB PNG, System Events answers, and
    TextEdit launches and is drivable. `managername` names the launchd DOMAIN,
    which depends on how the session was established (auto-login, NoMachine,
    a physical login all differ) - it is not a statement about window-server
    access, which is the thing we actually need.

    Gating on the proxy cost two hours and would have stopped the audit on a
    machine that was completely fine. So: probe the three capabilities the
    audit genuinely requires, and report the domain as INFO only.
    """
    import tempfile

    shot = os.path.join(tempfile.gettempdir(), "_cd_gui_probe.png")
    try:
        os.remove(shot)
    except OSError:
        pass
    rc, out = sh(["screencapture", "-x", shot], timeout=60)
    size = os.path.getsize(shot) if os.path.exists(shot) else 0
    add("window server reachable (screencapture)", size > 10_000, BLOCK,
        f"{size} bytes" + (f" - {out[:80]}" if out else ""),
        "No window server: nobody is logged in at the console, or the machine\n"
        "      is headless with no session. On a cloud Mac the usual cause is\n"
        "      auto-login not completing - check /etc/kcpassword exists and\n"
        "      `stat -f%Su /dev/console` returns your user, not root.")
    try:
        os.remove(shot)
    except OSError:
        pass

    rc, out = sh(["osascript", "-e",
                  'tell application "System Events" to return name of first process'],
                 timeout=60)
    add("AppleScript automation answers", rc == 0 and bool(out.strip()), BLOCK,
        out[:80] or "no answer",
        "osascript cannot reach the GUI, so no Office conversion can run.")

    rc, out = sh(["osascript", "-e",
                  'tell application "System Events" to return count of processes'],
                 timeout=60)
    add("GUI apps are enumerable", rc == 0, WARN, out[:80])

    rc, console_user = sh(["stat", "-f%Su", "/dev/console"])
    add("someone is logged in at the console", console_user.strip() not in ("", "root"),
        BLOCK, console_user.strip(),
        "A headless Mac with no console session has no framebuffer at all -\n"
        "      screen sharing shows black and GUI automation is impossible.\n"
        "      Enable auto-login: write /etc/kcpassword and reboot.")

    # Can a capture actually RENDER a window? Reaching the window server is not
    # the same as being able to see it. Measured on a Scaleway Mac over
    # NoMachine 2026-08-10: 12 windows listed, `screencapture` returned the bare
    # desktop every time, and `-l <winid>` refused. WARN not BLOCK - the audit
    # still runs, it just cannot answer visual questions itself, and the honest
    # response is to ask the operator rather than to read a blank PNG as a blank
    # app. That misreading would manufacture a CRITICAL against the packaged
    # app's WKWebView rendering, which is phase M3's highest-value check.
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from mac_eyes import eyesight                       # noqa: PLC0415
        _eye = eyesight()
        add("screenshots can render window content", _eye["ok"], WARN,
            f'{_eye.get("window_capture")} ({_eye.get("windows")} window(s), '
            f'target {_eye.get("target")})',
            "A remote-desktop display driver is intercepting composition. Hand\n"
            "      every visual question to the human; check with\n"
            "      `python3 scripts/mac_eyes.py eyesight`.")
    except Exception as e:                                     # noqa: BLE001
        add("screenshots can render window content", False, WARN,
            f"probe failed: {type(e).__name__}: {e}"[:160])

    # INFO only, deliberately. See the docstring - this is not a gate.
    rc, out = sh(["launchctl", "managername"])
    results.append({"check": "launchd domain", "ok": True, "severity": INFO,
                    "detail": (out.strip() or "unknown") +
                              "  (informational - NOT a gate; see check_gui_session)",
                    "fix": ""})


# ───────────────────────────────────────────────────────── python + deps

def check_python():
    v = sys.version_info
    add("Python 3.11", (v.major, v.minor) == (3, 11), WARN,
        f"{v.major}.{v.minor}.{v.micro}",
        "CI builds the .app on 3.11. Another minor version can resolve "
        "different native wheels than the release.")
    add("running inside the audit venv",
        "VIRTUAL_ENV" in os.environ or "venv" in sys.prefix, WARN, sys.prefix,
        "source .venv/bin/activate")

    missing, broken = [], []
    mods = ["streamlit", "canvasapi", "requests", "aiohttp", "aiofiles", "bs4",
            "markdownify", "moviepy", "imageio_ffmpeg", "keyring", "psutil",
            "openpyxl", "webview", "playwright", "objc", "faster_whisper",
            "ctranslate2", "onnxruntime", "huggingface_hub", "PIL", "numpy"]
    for m in mods:
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
        except Exception as e:                               # noqa: BLE001
            broken.append(f"{m} ({type(e).__name__}: {e})")
    add("every runtime import resolves", not missing and not broken, BLOCK,
        f"missing={missing or 'none'} broken={broken or 'none'}",
        "pip install -r requirements.txt   (and see the pyobjc note in it)")

    # pyobjc-framework-* must all share one version or UserNotifications
    # silently degrades to the deprecated NSUserNotification path.
    try:
        import objc
        core = objc.__version__
        try:
            import UserNotifications  # noqa: F401
            un_ok = True
        except Exception:                                     # noqa: BLE001
            un_ok = False
        add("UserNotifications binding imports", un_ok, WARN, f"pyobjc-core {core}",
            f'pip install "pyobjc-framework-UserNotifications=={core}"')
    except Exception:                                         # noqa: BLE001
        pass


def check_app_modules():
    sys.path.insert(0, str(REPO))
    bad = []
    for m in ("shared.helpers", "shared.shortcuts", "engine.applescript_bridge",
              "core.canvas_logic", "core.sync_manager", "panopto.runner",
              "panopto.shortcut", "converters.post_processing", "ui.auth"):
        try:
            __import__(m)
        except Exception as e:                                # noqa: BLE001
            bad.append(f"{m}: {type(e).__name__}: {e}")
    add("app modules import", not bad, BLOCK, "; ".join(bad) or "all ok")


# ────────────────────────────────────────────────────────────── tooling

def check_tooling():
    for tool, sev, why in (("git", BLOCK, ""), ("tmux", WARN,
                           "Without tmux an SSH drop kills the run."),
                           ("osascript", BLOCK, "")):
        add(f"{tool} present", shutil.which(tool) is not None, sev,
            shutil.which(tool) or "not found", why)

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        rc, out = sh([exe, "-version"], timeout=30)
        add("bundled ffmpeg runs", rc == 0, BLOCK, out.splitlines()[0] if out else "",
            "Panopto mp3/mp4 download goes through this binary.")
    except Exception as e:                                    # noqa: BLE001
        add("bundled ffmpeg runs", False, BLOCK, str(e))

    # Playwright's Chromium - the audit drives the app through it over CDP.
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
        add("Playwright Chromium installed", Path(exe).exists(), BLOCK, exe,
            "python -m playwright install chromium")
    except Exception as e:                                    # noqa: BLE001
        add("Playwright Chromium installed", False, BLOCK, str(e),
            "python -m playwright install chromium")


# ─────────────────────────────────────────────────────────────── Office

OFFICE = {"Microsoft Word": "convert_word",
          "Microsoft Excel": "convert_excel",
          "Microsoft PowerPoint": "convert_pptx"}


def check_office():
    for app in OFFICE:
        p = Path(f"/Applications/{app}.app")
        ver = ""
        if p.exists():
            try:
                info = plistlib.loads((p / "Contents" / "Info.plist").read_bytes())
                ver = info.get("CFBundleShortVersionString", "")
            except Exception:                                 # noqa: BLE001
                pass
        add(f"{app} installed", p.exists(), WARN, ver or str(p),
            "The converter phase is the highest-risk macOS subsystem; without "
            "Office it cannot run at all.")

    # Automation (TCC) - probe WITHOUT launching anything. A `get name` on a
    # not-running app returns quickly; the point is the error CODE:
    #   -1743 = user denied, -1744/-600 = not authorised yet / not running.
    for app in OFFICE:
        if not Path(f"/Applications/{app}.app").exists():
            continue
        rc, out = sh(["osascript", "-e",
                      f'tell application "System Events" to return '
                      f'exists application process "{app}"'], timeout=15)
        denied = "-1743" in out
        add(f"Automation not DENIED for {app}", not denied, BLOCK if denied else INFO,
            out[:120] or "no error",
            "System Settings > Privacy & Security > Automation - re-enable, or\n"
            "      tccutil reset AppleEvents  (then re-grant on next prompt)")


def check_tcc():
    tcc = Path.home() / "Library/Application Support/com.apple.TCC/TCC.db"
    try:
        with open(tcc, "rb") as fh:
            fh.read(1)
        fda = True
    except Exception:                                          # noqa: BLE001
        fda = False
    add("Full Disk Access for this terminal", fda, WARN, str(tcc),
        "System Settings > Privacy & Security > Full Disk Access > add\n"
        "      Terminal.app (or iTerm). Without it the app's own FDA probe\n"
        "      reports False and the macOS 15 nudge renders - which is worth\n"
        "      seeing ONCE deliberately, then granting.")


# ───────────────────────────────────────────────── credentials + repo

def _bounded(fn, *args, timeout=15.0):
    """Run *fn* on a daemon thread; return ('ok'|'err'|'timeout', value).

    A Keychain call can BLOCK on an interactive prompt - which is precisely
    what `ui.auth._run_keyring_op` exists to defend against, and the reason it
    uses a daemon thread rather than a pool (a pool's __exit__ joins and so
    defeats its own watchdog). A preflight that can hang is worse than one that
    lies, and for an UNATTENDED audit "it prompted" and "it is unusable" are the
    same answer, so a timeout is a real verdict here, not an inconclusive one.
    """
    import queue as _q
    import threading as _t
    box: _q.Queue = _q.Queue(maxsize=1)

    def _worker():
        try:
            box.put(("ok", fn(*args)))
        except Exception as e:                                 # noqa: BLE001
            box.put(("err", e))

    _t.Thread(target=_worker, daemon=True, name="doctor-keychain").start()
    try:
        return box.get(timeout=timeout)
    except _q.Empty:
        return ("timeout", timeout)


def check_keychain_session():
    """Can THIS process use the login Keychain at all? Round-trip our own item.

    This is the one macOS service scoped to the **security session** rather
    than to the framebuffer, which is why `check_gui_session`'s "test the
    capability, never a proxy" reasoning does not carry over to it. Measured on
    a Scaleway Apple-silicon Mac 2026-08-10, in ONE shell:

        screencapture                  -> a real 4.4 MB PNG
        System Events                  -> answers
        keyring.set_password(NEW item) -> errSecInteractionNotAllowed (-25308)

    A tmux server started over SSH is a `Background` session that can drive the
    entire GUI and cannot touch the Keychain. The app under test is a child of
    that shell, so token save "fails", auto-login "does not restore" and the
    90 s watchdog looks like it is being hit - none of it the product. The
    doctor reported READY in exactly that state, which is what this check is
    for.

    A brand-new item of our own making needs no ACL authorisation and no
    password, so a failure here is the session and nothing else.
    """
    try:
        import keyring
    except Exception as e:                                     # noqa: BLE001
        add("Keychain usable from this session", False, BLOCK,
            f"keyring import failed: {type(e).__name__}: {e}")
        return
    service, account = "CanvasDownloaderAuditProbe", "session-capability"

    def _round_trip():
        keyring.set_password(service, account, "probe")
        got = keyring.get_password(service, account)
        keyring.delete_password(service, account)
        return got

    kind, value = _bounded(_round_trip)
    if kind == "ok":
        ok = value == "probe"
        detail = ("set/get/delete round trip ok" if ok
                  else "round trip returned a different value")
    elif kind == "timeout":
        ok, detail = False, (f"blocked for {value:.0f}s - something is prompting; "
                             "an unattended audit cannot answer it")
    else:
        ok, detail = False, f"{type(value).__name__}: {value}"[:200]
    add("Keychain usable from this session", ok, BLOCK, detail,
        "Start tmux from a Terminal INSIDE the graphical session so every pane\n"
        "      inherits Aqua, or route the app through\n"
        "      `python3 scripts/mac_aqua.py run '<cmd>'`. Check either with\n"
        "      `python3 scripts/mac_aqua.py check`.")


def check_credentials():
    """The token must already be in the login Keychain, or every run stops at
    the login wall - which is exactly what makes an unattended audit fail."""
    settings = REPO / "canvas_downloader_settings.json"
    url = ""
    if settings.is_file():
        try:
            url = (json.loads(settings.read_text(encoding="utf-8"))
                   .get("api_url", "") or "")
        except Exception:                                      # noqa: BLE001
            pass
    add("canvas_downloader_settings.json has api_url", bool(url), BLOCK, url or "absent",
        "The audit seeds its isolated config from this file (SEEDED_FROM_REAL).")

    if not url:
        return
    rc, out = sh(["security", "find-generic-password", "-s", "CanvasDownloader",
                  "-a", url, "-w"], timeout=20)
    have = rc == 0 and out.strip() != ""
    add("Canvas token in the login Keychain", have, BLOCK, "present" if have else "absent",
        f'python3 -c "import keyring; keyring.set_password('
        f"'CanvasDownloader', '{url}', '<TOKEN>')\"    (see the next check for "
        f"why NOT /usr/bin/security)")

    # Probe with the client the CONSUMERS use, not with the tool that wrote it.
    #
    # `security find-generic-password` above reads an item CREATED by
    # /usr/bin/security silently, because the item's ACL names that binary. The
    # app and the harness's O5 client are **python**, which is not on that ACL -
    # so macOS asks to authorise it, and authorising an ACL change requires the
    # *login keychain's own password*. On a cloud image that is frequently the
    # image's original password and nobody has it, so the honest answer is
    # "unreadable". Measured 2026-08-10: `security` said present, python got
    # -25308 headless and a password prompt in Aqua, and the doctor said READY.
    #
    # Same class as CLAUDE.md's rule about verifying the real thing rather than
    # a copy: a probe that uses a different client than every consumer is not a
    # probe of anything.
    if have:
        try:
            import keyring
            kind, value = _bounded(keyring.get_password, "CanvasDownloader", url)
            if kind == "ok":
                py_ok = bool(value)
                py_detail = ("readable by python" if value
                             else "python read returned nothing")
            elif kind == "timeout":
                py_ok = False
                py_detail = (f"blocked for {value:.0f}s - macOS is asking to "
                             "authorise python against an item it did not create")
            else:
                py_ok, py_detail = False, f"{type(value).__name__}: {value}"[:200]
        except Exception as e:                                 # noqa: BLE001
            py_ok, py_detail = False, f"{type(e).__name__}: {e}"[:200]
        add("...and readable by PYTHON (the app's own client)", py_ok, BLOCK, py_detail,
            "An item written by /usr/bin/security is not readable by python\n"
            "      without the login keychain password. Delete it and let the app\n"
            "      create its own by logging in once through the UI (highest\n"
            "      fidelity), or re-seed it with python keyring:\n"
            "        security delete-generic-password -s CanvasDownloader "
            f'-a "{url}"\n'
            "        python3 -c \"import keyring; keyring.set_password("
            f"'CanvasDownloader', '{url}', '<TOKEN>')\"")

    if have:
        token = out.strip()
        rc2, out2 = sh(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                        "-H", f"Authorization: Bearer {token}",
                        f"{url.rstrip('/')}/api/v1/users/self"], timeout=30)
        add("Canvas API answers 200", out2.strip() == "200", BLOCK, f"HTTP {out2.strip()}",
            "Token expired or revoked - mint a new one in Canvas.")


def check_repo():
    rc, head = sh(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"])
    rc2, dirty = sh(["git", "-C", str(REPO), "status", "--porcelain"])
    add("repo checked out", rc == 0, BLOCK, head)
    add("working tree clean", dirty.strip() == "", WARN,
        f"{len(dirty.splitlines())} modified file(s)",
        "Uncommitted work here will not match what you audited later.")
    rc3, behind = sh(["git", "-C", str(REPO), "rev-list", "--count", "HEAD..@{u}"])
    if rc3 == 0:
        add("up to date with origin", behind.strip() in ("0", ""), WARN,
            f"{behind.strip()} commit(s) behind", "git pull")

    free = shutil.disk_usage(REPO).free / 1e9
    add("disk space", free > 25, WARN, f"{free:.1f} GB free",
        "A Panopto mp4 row alone writes ~2.2 GB; snapshots and lanes multiply it.")


def check_harness():
    """The audit CLI must import and answer - a broken harness reads as a
    broken app for the first hour."""
    rc, out = sh([sys.executable, "-m", "tests.audit", "--help"], timeout=90)
    add("audit harness responds", rc == 0, BLOCK, (out.splitlines() or [""])[0],
        "cd into the repo root and re-run; the harness is a package.")


# ─────────────────────────────────────────────────────────────── output

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quick", action="store_true",
                    help="skip the network and Office probes")
    args = ap.parse_args()

    check_platform()
    if sys.platform == "darwin":
        check_gui_session()
        check_keychain_session()
    check_python()
    check_app_modules()
    check_tooling()
    if not args.quick:
        check_office()
        check_tcc()
        check_credentials()
    check_repo()
    check_harness()

    blocking = [r for r in results if not r["ok"] and r["severity"] == BLOCK]
    warns = [r for r in results if not r["ok"] and r["severity"] == WARN]

    if args.json:
        print(json.dumps({"ready": not blocking, "blocking": len(blocking),
                          "warnings": len(warns), "results": results}, indent=2))
        return 1 if blocking else 0

    width = max(len(r["check"]) for r in results) + 2
    print("\n  CANVAS DOWNLOADER - macOS audit preflight")
    print("  " + "-" * (width + 46))
    for r in results:
        mark = "ok  " if r["ok"] else ("FAIL" if r["severity"] == BLOCK else "warn")
        print(f"  [{mark}] {r['check']:<{width}} {r['detail'][:64]}")
    print("  " + "-" * (width + 46))

    if blocking or warns:
        print()
        for r in blocking + warns:
            tag = "BLOCKING" if r["severity"] == BLOCK else "warning"
            print(f"  {tag}: {r['check']}")
            print(f"      {r['detail']}")
            if r["fix"]:
                print(f"      fix: {r['fix']}")
            print()

    if blocking:
        print(f"  NOT READY - {len(blocking)} blocking issue(s).\n")
        return 1
    print(f"  READY{f' ({len(warns)} warning(s) - note them in the findings)' if warns else ''}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
