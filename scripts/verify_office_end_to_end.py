"""The whole Office story, end to end, in the two states a user is really in.

Everything else in this repo tests one mechanism. This drives a REAL conversion
phase through `run_all_conversions` - the same entry point the download and
sync flows use - across Word, Excel AND PowerPoint, and checks the four things
that actually matter to a user:

  1. the files convert;
  2. a document the USER has open and unsaved is never touched;
  3. the Office apps we launched are quit afterwards, and one the user is
     working in is NOT;
  4. our temp files are gone from Office's Recents list.

TWO STARTING STATES, because they exercise opposite halves:

    --state cold   no Office app running. Everything must convert, every app we
                   launched must be quit, and Recents must come out clean.
    --state busy   the user is editing a REAL document in each of the three
                   apps first. Their documents must survive; the apps must be
                   LEFT RUNNING; and Recents must still be cleaned for the apps
                   that are not running - which is why the purge is per-app.

    python scripts/verify_office_end_to_end.py --state cold
    python scripts/verify_office_end_to_end.py --state busy
    python scripts/verify_office_end_to_end.py --state busy --apps PowerPoint

The user documents are created by this script in a temp directory. Nothing of
the operator's is opened, edited or closed.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

MARK = "CanvasDownloaderTmp"
REG = Path.home() / "Library" / "Group Containers" / "UBF8T346G9.Office" \
    / "MicrosoftRegistrationDB.reg"

APPS = {
    "Word": ("Microsoft Word", "document", ".doc", "convert_word"),
    "Excel": ("Microsoft Excel", "workbook", ".xlsx", "convert_excel"),
    "PowerPoint": ("Microsoft PowerPoint", "presentation", ".pptx", "convert_pptx"),
}


def _osa(script: str, timeout: float = 90) -> str:
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr or "").strip()
    except Exception as e:                      # noqa: BLE001
        return f"ERR {e}"


def _running(bundle: str) -> bool:
    return subprocess.run(["pgrep", "-x", bundle], capture_output=True).returncode == 0


def _quit_all() -> None:
    for _s, (bundle, *_r) in APPS.items():
        _osa(f'tell application "{bundle}" to quit saving no', timeout=45)
    time.sleep(2)
    for _s, (bundle, *_r) in APPS.items():
        subprocess.run(["pkill", "-x", bundle], capture_output=True)
    time.sleep(1.5)


def _recents_ours() -> int:
    """Our entries currently in Office's Recents list."""
    if not REG.is_file():
        return -1
    try:
        c = sqlite3.connect(f"file:{REG}?mode=ro", uri=True)
        n = sum(1 for (name,) in c.execute("SELECT name FROM HKEY_CURRENT_USER")
                if name and MARK in str(name))
        c.close()
        return n
    except Exception:                           # noqa: BLE001
        return -1


def _samples(ext: str, n: int) -> list[Path]:
    out, seen = [], set()
    for p in (REPO / "_audit_runs").rglob(f"*{ext}"):
        if p.is_file() and 20_000 < p.stat().st_size < 8_000_000 and p.name not in seen:
            seen.add(p.name)
            out.append(p)
            if len(out) >= n:
                break
    return out


def _legacy_doc(work: Path, tag: str) -> Path | None:
    """`textutil -convert doc` makes a genuine legacy .doc Word opens silently;
    a hand-built one triggers the repair modal and hangs."""
    txt = work / f"{tag}.txt"
    txt.write_text(f"Canvas Downloader {tag}.\n" * 40, encoding="utf-8")
    out = work / f"{tag}.doc"
    r = subprocess.run(["textutil", "-convert", "doc", "-output", str(out), str(txt)],
                       capture_output=True, timeout=60)
    return out if (r.returncode == 0 and out.exists()) else None


def _open_user_doc(app: str, work: Path) -> Path | None:
    """A REAL document of the user's, opened and made dirty."""
    bundle, klass, ext, _key = APPS[app]
    src = _legacy_doc(work, f"user_{app}") if app == "Word" else \
        (_samples(ext, 1) or [None])[0]
    if src is None:
        return None
    doc = work / f"MY {app.upper()} WORK{src.suffix}"
    shutil.copy2(src, doc)
    _osa(f'tell application "{bundle}" to open POSIX file "{doc}"', timeout=120)
    time.sleep(3)
    dirty = {
        "Word": 'tell application "Microsoft Word" to set content of text object '
                'of active document to "the user was editing this"',
        "Excel": 'tell application "Microsoft Excel" to set value of range "A1" '
                 'of active sheet to "the user was editing this"',
        "PowerPoint": 'tell application "Microsoft PowerPoint" to set name of '
                      'active presentation to (name of active presentation)',
    }[app]
    _osa(dirty, timeout=45)
    return doc


def _docs_open(app: str) -> int:
    bundle, klass, *_r = APPS[app]
    if not _running(bundle):
        return 0
    out = _osa(f'tell application "{bundle}"\n try\n return (count of {klass}s)\n'
               f' on error\n return -1\n end try\nend tell', timeout=30)
    try:
        return int(out)
    except ValueError:
        return -1


def main() -> int:
    if sys.platform != "darwin":
        print("macOS only", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", choices=("cold", "busy"), default="cold")
    ap.add_argument("--apps", action="append", choices=sorted(APPS))
    ap.add_argument("--files", type=int, default=3, help="per app")
    a = ap.parse_args()
    apps = a.apps or ["Word", "Excel", "PowerPoint"]

    work = Path(tempfile.mkdtemp(prefix="cd_e2e_"))
    course = work / "Course"
    course.mkdir()

    # The course folder, as a download would leave it.
    staged, expect = [], {}
    for app in apps:
        _b, _k, ext, _key = APPS[app]
        srcs = [_legacy_doc(work, f"src{app}{i}") for i in range(a.files)] \
            if app == "Word" else _samples(ext, a.files)
        srcs = [s for s in srcs if s]
        for i, s in enumerate(srcs):
            d = course / f"{app} Lecture {i + 1}{s.suffix}"
            shutil.copy2(s, d)
            staged.append(d)
        expect[app] = len(srcs)

    _quit_all()
    user_docs = {}
    if a.state == "busy":
        for app in apps:
            user_docs[app] = _open_user_doc(app, work)
    before_docs = {app: _docs_open(app) for app in apps}
    before_recents = _recents_ours()

    from core.sync_manager import SyncManager
    from converters.post_processing import run_all_conversions, UIBridge

    class _Sink:
        def __getattr__(self, _n):
            return lambda *x, **k: None

    log: list = []
    ui = UIBridge(header_placeholder=_Sink(), progress_placeholder=_Sink(),
                  metrics_placeholder=_Sink(), log_placeholder=_Sink(),
                  active_file_placeholder=_Sink(), log_lines=log)
    contract = {APPS[app][3]: True for app in apps}
    sm = SyncManager(str(course), 43660, "Course")

    t0 = time.time()
    run_all_conversions(course, sm, contract, ui, course_name="Course",
                        explicit_files=[str(p) for p in staged])
    convert_s = round(time.time() - t0, 1)

    # The app's own teardown - what the completion screen calls. It runs on a
    # DAEMON THREAD and returns immediately, and the Recents purge is its LAST
    # step: measured, it lands ~15s after the final process dies (wait-for-exit
    # plus the retry pass). The first version of this script broke out as soon
    # as `pgrep` was empty and then measured, which reported a working purge as
    # broken. Wait for the teardown's own outcome instead, bounded.
    from engine.applescript_bridge import quit_idle_office_apps
    t_teardown = time.time()
    quit_idle_office_apps()
    for _ in range(90):
        if _recents_ours() == 0 and not any(_running(APPS[x][0]) for x in apps):
            break
        time.sleep(1)
    teardown_s = round(time.time() - t_teardown, 1)

    plain = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(x))).strip() for x in log]
    per_app = {}
    for app in apps:
        _b, _k, ext, _key = APPS[app]
        left = sorted(p.name for p in course.glob(f"{app} Lecture*{ext}"))
        pdfs = sorted(p.name for p in course.glob(f"{app} Lecture*.pdf"))
        still_open = _docs_open(app)
        per_app[app] = {
            "sources": expect[app],
            "pdfs": len(pdfs),
            "sources_left": left,
            "app_running_after": _running(APPS[app][0]),
            "docs_before": before_docs[app],
            "docs_after": still_open,
            "user_document_survived": (
                None if a.state == "cold" else still_open >= 1),
        }

    from converters.verify import pdf_looks_real
    bad = [p.name for p in course.glob("*.pdf") if not pdf_looks_real(p)[0]]
    after_recents = _recents_ours()

    result = {
        "state": a.state, "apps": apps, "convert_seconds": convert_s,
        "converted_ok": ui.pp_success_count, "failed": ui.pp_failure_count,
        "unusable_pdfs": bad,
        "recents_ours_before": before_recents,
        "recents_ours_after": after_recents,
        "teardown_seconds": teardown_s,
        "per_app": per_app,
        "errors": [x[:110] for x in plain if "fail" in x.lower()][:5],
    }

    problems = []
    for app, r in per_app.items():
        if r["pdfs"] != r["sources"]:
            problems.append(f"{app}: {r['pdfs']}/{r['sources']} converted")
        if r["sources_left"]:
            problems.append(f"{app}: sources survived {r['sources_left']}")
        if a.state == "busy" and not r["user_document_survived"]:
            problems.append(f"{app}: THE USER'S DOCUMENT WAS CLOSED")
        if a.state == "busy" and not r["app_running_after"]:
            problems.append(f"{app}: quit an app the user was working in")
        if a.state == "cold" and r["app_running_after"]:
            problems.append(f"{app}: left running with no user document")
    if bad:
        problems.append(f"unusable PDFs: {bad}")
    if a.state == "cold" and after_recents > 0:
        problems.append(f"Recents still holds {after_recents} of our entries")
    result["problems"] = problems
    result["VERDICT"] = "ALL GOOD" if not problems else "PROBLEMS - see above"
    print(json.dumps(result, indent=1, ensure_ascii=False))

    _quit_all()
    shutil.rmtree(work, ignore_errors=True)
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
