#!/usr/bin/env python3
"""Every macOS check that can be made WITHOUT a human looking at the screen.

The audit matrices already drive download and sync. What was left manual is the
platform surface: Keychain, notifications, `.webloc` handling, HFS+/NFD paths,
Office reachability, process hygiene, and the packaged bundle's shape. Most of
that does not actually need eyes - it needs a real macOS, which is the thing
that was scarce.

    python3 scripts/mac_smoke.py                 # everything safe + fast
    python3 scripts/mac_smoke.py --with-hfs      # + a real HFS+ volume (NFD)
    python3 scripts/mac_smoke.py --with-office   # + launch/quit Office (slow)
    python3 scripts/mac_smoke.py --bundle "dist/Canvas Downloader.app"
    python3 scripts/mac_smoke.py --json

Run it AFTER `mac_audit_doctor.py` says READY. It is read-mostly: it writes
only inside a temp dir and (with --with-hfs) a disk image it detaches and
deletes. It never touches the audit's config dir or a real course folder.

WHAT IT DELIBERATELY DOES NOT COVER, because only a person can:
  - whether Finder actually opens a `.webloc`
  - whether a notification banner is visible
  - whether the app renders correctly in WKWebView
  - the folder picker's modal
Those stay in MAC_RUNBOOK.md phases M2/M3/M5.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PASS, FAIL, SKIP = "pass", "FAIL", "skip"
rows: list[dict] = []


def rec(section, name, status, detail=""):
    rows.append({"section": section, "check": name, "status": status,
                 "detail": str(detail)[:400]})
    mark = {PASS: "ok  ", FAIL: "FAIL", SKIP: "skip"}[status]
    print(f"  [{mark}] {name}" + (f"  -  {detail}"[:120] if detail else ""))
    return status == PASS


def sh(cmd, timeout=60, **kw):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as e:                                    # noqa: BLE001
        return 127, f"{type(e).__name__}: {e}"


def section(title):
    print(f"\n== {title}")


# ─────────────────────────────────────────────────── 1. paths & unicode

def check_paths(tmp: Path):
    section("Paths")
    from shared.helpers import make_long_path

    p = "/Users/x/Course/Lecture.mp4"
    rec("paths", "make_long_path is a no-op on macOS",
        PASS if make_long_path(p) == p else FAIL, make_long_path(p))

    # macOS allows 1024-char paths but only 255 BYTES per component - a
    # different limit from Windows, and one nothing has ever exercised.
    deep = tmp / ("d" * 200) / ("e" * 200) / ("f" * 200)
    try:
        deep.mkdir(parents=True)
        f = deep / ("g" * 200 + ".txt")
        f.write_text("x", encoding="utf-8")
        ok = f.exists() and len(str(f)) > 600
        rec("paths", "a >600 char path round-trips", PASS if ok else FAIL, f"{len(str(f))} chars")
    except OSError as e:
        rec("paths", "a >600 char path round-trips", FAIL, e)

    # 256-byte component must be REFUSED by the filesystem, not by us.
    try:
        (tmp / ("h" * 256)).write_text("x", encoding="utf-8")
        rec("paths", "a 256-byte component is refused by the FS", FAIL,
            "it was accepted - the 255-byte assumption is wrong on this volume")
    except OSError:
        rec("paths", "a 256-byte component is refused by the FS", PASS, "ENAMETOOLONG")


def check_unicode_apfs(tmp: Path):
    section("Unicode (APFS)")
    from core.sync_manager import _path_key

    name = "Forelæsning årsag økonomi.pdf"        # æ å ø
    f = tmp / name
    f.write_text("x", encoding="utf-8")
    back = next(p.name for p in tmp.iterdir() if p.suffix == ".pdf")

    rec("unicode", "APFS is normalisation-PRESERVING",
        PASS if back == name else SKIP,
        "os.walk returned the NFC we wrote" if back == name
        else f"returned {unicodedata.name(back[6], '?')}-form - not APFS?")

    rec("unicode", "_path_key agrees across NFC/NFD",
        PASS if _path_key(unicodedata.normalize("NFD", str(f)))
                == _path_key(unicodedata.normalize("NFC", str(f))) else FAIL)


def check_unicode_hfs():
    """The ONE place _path_key's NFC normalisation is not a no-op.

    APFS preserves what you wrote, so a modern Mac hides this completely. HFS+
    stores the decomposed form, and an external drive is an ordinary place to
    keep a course folder. A disk image gives us a real HFS+ volume for free.
    """
    section("Unicode (HFS+ disk image)")
    dmg = Path(tempfile.gettempdir()) / "cd_nfd_probe.dmg"
    vol = Path("/Volumes/NFDProbe")
    attached = False
    try:
        rc, out = sh(["hdiutil", "create", "-size", "60m", "-fs", "HFS+",
                      "-volname", "NFDProbe", "-ov", str(dmg)], timeout=180)
        if rc != 0:
            return rec("unicode-hfs", "create an HFS+ image", SKIP, out[:160])
        rc, out = sh(["hdiutil", "attach", str(dmg)], timeout=120)
        if rc != 0:
            return rec("unicode-hfs", "attach the HFS+ image", SKIP, out[:160])
        attached = True

        from core.sync_manager import _path_key
        name = "Forelæsning årsag økonomi.pdf"
        (vol / name).write_text("x", encoding="utf-8")
        back = next(p.name for p in vol.iterdir() if p.suffix == ".pdf")

        decomposed = back != name
        rec("unicode-hfs", "HFS+ hands back the DECOMPOSED name",
            PASS if decomposed else SKIP,
            "as expected - this is the case APFS hides"
            if decomposed else "volume did not decompose; probe inconclusive")

        same = _path_key(str(vol / name)) == _path_key(str(vol / back))
        rec("unicode-hfs", "_path_key maps both forms to ONE key",
            PASS if same else FAIL,
            "a tracked file would read as an orphan and inflate the "
            "untracked-files count" if not same else "")
    finally:
        if attached:
            sh(["hdiutil", "detach", str(vol), "-force"], timeout=120)
        dmg.unlink(missing_ok=True)


# ────────────────────────────────────────────────────── 2. shortcuts

def check_shortcuts(tmp: Path):
    section("Shortcuts (.webloc)")
    from shared.shortcuts import (read_shortcut, shortcut_extension,
                                  is_produced_shortcut, write_shortcut)
    from panopto.shortcut import resolve_shortcut_path

    rec("shortcuts", "native extension is .webloc",
        PASS if shortcut_extension() == ".webloc" else FAIL, shortcut_extension())

    p = tmp / "Lecture.webloc"
    write_shortcut(p, "https://panopto.example.edu/x", source="panopto")
    parsed = plistlib.loads(p.read_bytes())
    rec("shortcuts", "written file is a valid 2-key plist",
        PASS if parsed.get("URL") and len(parsed) == 2 else FAIL, sorted(parsed))
    rec("shortcuts", "round-trips through read_shortcut",
        PASS if read_shortcut(p) == ("https://panopto.example.edu/x", "panopto") else FAIL)
    rec("shortcuts", "recognised as app-produced",
        PASS if is_produced_shortcut(p) else FAIL)

    # `open -R` reveals rather than launching - proves the OS parses the file
    # without opening a browser tab we would then have to close.
    rc, out = sh(["open", "-R", str(p)], timeout=30)
    rec("shortcuts", "macOS accepts the file (open -R)",
        PASS if rc == 0 else FAIL,
        out[:140] or "Finder revealed it; whether double-click OPENS it is a "
                     "human check (MAC_RUNBOOK M2)")

    # A Windows-written .url in the same folder must be ADOPTED, not duplicated.
    write_shortcut(tmp / "FromWindows.url", "https://p/2", source="panopto")
    got = resolve_shortcut_path(tmp / "FromWindows")
    rec("shortcuts", "a Windows .url is adopted on macOS",
        PASS if got == tmp / "FromWindows.url" else FAIL, got)

    # The URL compiler must eat foreign links and spare ours.
    (tmp / "CanvasLink.webloc").write_bytes(
        plistlib.dumps({"URL": "https://example.edu/canvas"}))
    from converters.url import compile_urls_to_txt
    out_path, consumable = compile_urls_to_txt(tmp, "Course")
    names = {q.name for q in consumable}
    rec("shortcuts", "compiler consumes the Canvas link only",
        PASS if names == {"CanvasLink.webloc"} else FAIL, sorted(names))
    rec("shortcuts", "our .webloc and the Windows .url both survive",
        PASS if p.exists() and (tmp / "FromWindows.url").exists() else FAIL)


# ────────────────────────────────────────────────────── 3. AppleScript

def check_applescript(tmp: Path):
    section("AppleScript")
    from engine.applescript_bridge import applescript_string, _as_posix

    rc, out = sh(["osascript", "-e", "return 6 * 7"], timeout=20)
    rec("applescript", "osascript answers", PASS if out.strip() == "42" else FAIL, out[:120])

    # A filename macOS permits but an AppleScript literal cannot contain.
    nasty = tmp / 'Say "hi"\rand bye.txt'
    try:
        nasty.write_text("x", encoding="utf-8")
        lit = _as_posix(nasty)
        rc, out = sh(["osascript", "-e", f'return POSIX file "{lit}" as text'], timeout=20)
        rec("applescript", "a quote+CR filename survives the literal",
            PASS if rc == 0 else FAIL, out[:140])
    except OSError as e:
        rec("applescript", "a quote+CR filename survives the literal", SKIP, e)

    # The escaper fixed 2026-08-10; this is its first run on real osascript.
    body = applescript_string('Statistik\r2025 "A"')
    rc, out = sh(["osascript", "-e", f'return "{body}"'], timeout=20)
    rec("applescript", "applescript_string output compiles",
        PASS if rc == 0 else FAIL, out[:140])


def check_office(with_office: bool):
    section("Office")
    apps = ["Microsoft Word", "Microsoft Excel", "Microsoft PowerPoint"]
    for a in apps:
        rec("office", f"{a} installed",
            PASS if Path(f"/Applications/{a}.app").exists() else SKIP)

    if not with_office:
        rec("office", "Automation reachability", SKIP, "pass --with-office (launches apps)")
        return

    for a in apps:
        if not Path(f"/Applications/{a}.app").exists():
            continue
        rc, out = sh(["osascript", "-e", f'tell application "{a}" to return version'],
                     timeout=180)
        rec("office", f"Automation works for {a}", PASS if rc == 0 else FAIL, out[:140])

    from engine.applescript_bridge import quit_idle_office_apps
    quit_idle_office_apps()
    rc, out = sh(["pgrep", "-fl", "Microsoft (Word|Excel|PowerPoint)"], timeout=30)
    rec("office", "no Office process left running",
        PASS if not out.strip() else FAIL, out[:200])


# ──────────────────────────────────────────── 4. keychain, notifications

def check_keychain():
    section("Keychain")
    import ui.auth as A
    probe_user = "https://smoke-probe.invalid"
    try:
        ok_set = A._safe_keyring_set(A.KEYRING_SERVICE, probe_user, "SMOKE-VALUE")
        got = A._safe_keyring_get(A.KEYRING_SERVICE, probe_user)
        rec("keychain", "write then read round-trips",
            PASS if ok_set and got == "SMOKE-VALUE" else FAIL, repr(got))
    finally:
        try:
            A._safe_keyring_delete(A.KEYRING_SERVICE, probe_user)
        except Exception:                                      # noqa: BLE001
            pass
    rec("keychain", "probe item deleted",
        PASS if not A._safe_keyring_get(A.KEYRING_SERVICE, probe_user) else FAIL)

    rec("keychain", "macOS watchdog is the long one",
        PASS if A._KEYRING_TIMEOUT == 90.0 else FAIL, A._KEYRING_TIMEOUT)

    # The disk fallback is Windows-only BY DESIGN - a token must never land on
    # a macOS disk when Keychain is unavailable.
    #
    # Import get_config_dir from where it LIVES. The first version read it off
    # ui.auth behind a `hasattr` guard; ui.auth does not re-export it, so the
    # guard was always False, `leaked` was always empty, and the check reported
    # PASS while inspecting nothing at all.
    from shared.helpers import get_config_dir
    cfg = Path(get_config_dir())
    A._save_fallback_token(probe_user, "SHOULD-NEVER-BE-WRITTEN")
    leaked = [q for q in cfg.glob(".token_fallback*")]
    also = [q for q in cfg.rglob("*") if q.is_file()
            and "SHOULD-NEVER-BE-WRITTEN" in q.read_text(errors="replace")]
    rec("keychain", "no token fallback file on macOS",
        PASS if not leaked and not also else FAIL,
        f"searched {cfg}: {leaked or also}")


def check_notifications():
    section("Notifications")
    import engine.notifications as N
    # Which link of the chain wins is the interesting question; pync is
    # documented as unreliable on arm64 Sequoia.
    try:
        won = "UNUserNotifications" if N._show_macos_notification_un(
            "Canvas Downloader smoke", "chain probe") else None
    except Exception as e:                                     # noqa: BLE001
        won = None
        rec("notifications", "UNUserNotifications path", FAIL, e)
    if won:
        rec("notifications", "UNUserNotifications delivered", PASS,
            "a banner should be visible - confirm by eye (MAC_RUNBOOK M5)")
    else:
        try:
            nat = N._show_macos_notification_native("Canvas Downloader smoke", "chain probe")
        except Exception as e:                                 # noqa: BLE001
            nat = False
            rec("notifications", "NSUserNotification path", FAIL, e)
        rec("notifications", "fell back to NSUserNotification",
            PASS if nat else SKIP,
            "modern path unavailable - check the pyobjc UserNotifications pin")

    # The osascript fallback was fixed 2026-08-10 and has never run on a Mac.
    from engine.applescript_bridge import applescript_string
    script = (f'display notification "{applescript_string("body 2025 A")}" '
              f'with title "Canvas Downloader" '
              f'subtitle "{applescript_string("Statistik 2025")}"')
    rc, out = sh(["osascript", "-e", script], timeout=30)
    rec("notifications", "the osascript fallback compiles and runs",
        PASS if rc == 0 else FAIL, out[:140])


# ───────────────────────────────────────────────── 5. media + hardware

def check_media():
    section("Media")
    from panopto.stream import ffmpeg_exe
    exe = ffmpeg_exe()
    rc, out = sh([exe, "-version"], timeout=60)
    rec("media", "bundled ffmpeg runs on arm64", PASS if rc == 0 else FAIL,
        (out.splitlines() or [""])[0][:120])

    rc, out = sh(["file", exe], timeout=30)
    rec("media", "ffmpeg binary architecture", PASS if rc == 0 else SKIP, out[:140])


def check_hardware():
    section("Compute hardware")
    import panopto.hardware as HW
    hw = HW.detect_compute_hardware(force=True)
    rec("hardware", "probe returns a dict", PASS if isinstance(hw, dict) and hw else FAIL)
    rec("hardware", "reports macOS", PASS if hw.get("is_mac") else FAIL,
        f"arm_mac={hw.get('is_arm_mac')}")
    rec("hardware", "no CUDA claimed on Apple silicon",
        PASS if not hw.get("gpu_available") else FAIL, hw.get("gpu_reason", ""))
    rec("hardware", "recommends the CPU path",
        PASS if hw.get("recommended_device") == "cpu" else FAIL,
        hw.get("recommended_device"))

    # ctranslate2 co-loaded with numpy/streamlit segfaults from an OpenMP
    # clash - which is exactly why transcription runs out of process. Probe it
    # in a CLEAN interpreter so a crash here cannot take this script with it.
    code = ("import ctranslate2, faster_whisper, sys;"
            "print('ct2', ctranslate2.__version__)")
    rc, out = sh([sys.executable, "-c", code], timeout=180)
    rec("hardware", "ctranslate2 imports in a clean process",
        PASS if rc == 0 else FAIL, out[:160])


# ─────────────────────────────────────────────── 6. the packaged bundle

def check_bundle(bundle: Path):
    section(f"Packaged bundle - {bundle.name}")
    if not bundle.is_dir():
        return rec("bundle", "bundle exists", SKIP, f"{bundle} not built yet")
    rec("bundle", "bundle exists", PASS, bundle)

    info = bundle / "Contents" / "Info.plist"
    try:
        plist = plistlib.loads(info.read_bytes())
        rec("bundle", "Info.plist parses", PASS,
            f"{plist.get('CFBundleIdentifier')} {plist.get('CFBundleShortVersionString')}")
        rec("bundle", "has a bundle identifier",
            PASS if plist.get("CFBundleIdentifier") else FAIL,
            "UNUserNotificationCenter needs one or notifications degrade")
        rec("bundle", "minimum system version declared",
            PASS if plist.get("LSMinimumSystemVersion") else SKIP,
            plist.get("LSMinimumSystemVersion", ""))
    except Exception as e:                                     # noqa: BLE001
        rec("bundle", "Info.plist parses", FAIL, e)

    rc, out = sh(["codesign", "--verify", "--deep", "--strict", "--verbose=2",
                  str(bundle)], timeout=300)
    rec("bundle", "code signature verifies", PASS if rc == 0 else FAIL, out[:200])

    rc, out = sh(["codesign", "-d", "--entitlements", ":-", str(bundle)], timeout=120)
    rec("bundle", "apple-events entitlement present",
        PASS if "apple-events" in out else FAIL,
        "Office automation is refused without it")

    # The transcription worker is routed by env var because a .app drops argv.
    worker = bundle / "Contents" / "MacOS" / "Canvas_Downloader_Worker"
    rec("bundle", "transcription worker binary shipped",
        PASS if worker.exists() else SKIP, worker.name)

    # WKWebView cannot parse Streamlit's lookbehind regex; the build patches it.
    static = list(bundle.rglob("static/js/index.*.js"))
    if static:
        txt = static[0].read_text(encoding="utf-8", errors="replace")
        rec("bundle", "WebKit lookbehind patch applied",
            PASS if "(?<=" not in txt else FAIL,
            "an unpatched lookbehind leaves the UI blank in WKWebView")
    else:
        rec("bundle", "WebKit lookbehind patch applied", SKIP, "index js not found")

    idx = list(bundle.rglob("streamlit/static/index.html"))
    if idx:
        html = idx[0].read_text(encoding="utf-8", errors="replace")
        rec("bundle", "boot splash injected",
            PASS if "_cdBoot" in html or "prerenderReady" in html else FAIL)
        rec("bundle", "no tornado template opener in index.html",
            PASS if not any(t in html for t in ("{{", "{%", "{#")) else FAIL,
            "a stray opener takes the 404 page down")


# ─────────────────────────────────────────────────────── 7. hygiene

def check_processes():
    section("Process hygiene")
    rc, out = sh(["pgrep", "-fl", "-i", "canvas"], timeout=30)
    lines = [l for l in out.splitlines() if "mac_smoke" not in l and "pgrep" not in l]
    rec("processes", "no stray Canvas Downloader processes",
        PASS if not lines else FAIL, "; ".join(lines)[:200])
    rc, out = sh(["pgrep", "-fl", "ffmpeg"], timeout=30)
    rec("processes", "no orphaned ffmpeg", PASS if not out.strip() else FAIL, out[:200])

    dup = Path.home() / "Library/Application Support/CanvasDownloader/duplicate_launches.log"
    n = len(dup.read_text(errors="replace").splitlines()) if dup.is_file() else 0
    rec("processes", "no duplicate GUI launches recorded",
        PASS if n == 0 else FAIL, f"{n} line(s) in duplicate_launches.log")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--with-hfs", action="store_true",
                    help="create a real HFS+ disk image to test NFD paths")
    ap.add_argument("--with-office", action="store_true",
                    help="launch and quit Office (slow, needs Automation grants)")
    ap.add_argument("--bundle", default="dist/Canvas Downloader.app")
    args = ap.parse_args()

    if sys.platform != "darwin":
        print("mac_smoke.py only means anything on macOS.", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="cd_mac_smoke_"))
    try:
        check_paths(tmp)
        check_unicode_apfs(Path(tempfile.mkdtemp(prefix="cd_uni_")))
        if args.with_hfs:
            check_unicode_hfs()
        check_shortcuts(Path(tempfile.mkdtemp(prefix="cd_sc_")))
        check_applescript(tmp)
        check_office(args.with_office)
        check_keychain()
        check_notifications()
        check_media()
        check_hardware()
        check_bundle(Path(args.bundle) if Path(args.bundle).is_absolute()
                     else REPO / args.bundle)
        check_processes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in rows if r["status"] == FAIL]
    skipped = [r for r in rows if r["status"] == SKIP]
    if args.json:
        print(json.dumps({"failed": len(failed), "skipped": len(skipped),
                          "passed": len(rows) - len(failed) - len(skipped),
                          "rows": rows}, indent=2))
    else:
        print(f"\n{'='*70}")
        print(f"  {len(rows)-len(failed)-len(skipped)} passed | "
              f"{len(failed)} FAILED | {len(skipped)} skipped")
        for r in failed:
            print(f"\n  FAILED [{r['section']}] {r['check']}\n         {r['detail']}")
        print(f"{'='*70}\n")
        print("  Still needs a human (MAC_RUNBOOK M2/M3/M5): does Finder OPEN a")
        print("  .webloc, is the notification banner visible, does the app render")
        print("  correctly in WKWebView, and the folder picker's modal.\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
