"""The whole Office story, end to end, in the states a user is really in.

Everything else in this repo tests one mechanism. This drives a REAL conversion
phase through `run_all_conversions` - the same entry point the download and
sync flows use - across Word, Excel AND PowerPoint, and checks the four things
that actually matter to a user:

  1. the files convert;
  2. a document the USER has open and unsaved is never touched;
  3. the Office apps we launched are quit afterwards, and one the user is
     working in is NOT;
  4. our temp files are gone from Office's Recents list.

**EVERY STATE NOW GOES THROUGH THE APP'S OWN RUN-START SEQUENCE** - that is
`reset_office_priming()` -> `first_run_permission_setup()` -> (per course)
`prime_office_automation()`, exactly as `app.py` and `sync/execution.py`
sequence it. Until 2026-08-13 this script called `run_all_conversions` directly
and primed nothing, which is precisely why it could not see the D11 defect
(*"every harness in this repo passed, because they drive the converters
directly and never prime"*). Priming launches all three apps, so who-launched-
what is decided by that sequence and not by the converters.

FOUR STATES, because they exercise different halves:

    --state cold      no Office app running. Everything must convert, every app
                      we launched must be quit, and Recents must come out clean.
    --state busy      the user is editing a REAL document in each of the three
                      apps first. Their documents must survive; the apps must be
                      LEFT RUNNING; and Recents must still be cleaned for the
                      apps that are not running - which is why the purge is
                      per-app.
    --state two-runs  MAC_RUNBOOK Phase M1 step 8(b) - THE DATA-LOSS PATH, and
                      the reason this script exists in its current form. Two
                      complete runs in ONE PROCESS with the user opening Word in
                      between. `pkill`ing between runs is NOT a substitute: the
                      bug was per-PROCESS state surviving into run 2, so a
                      restart hides it.
    --state cancel    MAC_RUNBOOK Phase M1 step 8(c). The teardown fires on the
                      cancelled screens too. An app we never observed at all
                      must be left alone - it used to count as ours.

    python scripts/verify_office_end_to_end.py --state cold
    python scripts/verify_office_end_to_end.py --state busy
    python scripts/verify_office_end_to_end.py --state two-runs
    python scripts/verify_office_end_to_end.py --state cancel
    python scripts/verify_office_end_to_end.py --state busy --apps PowerPoint

For step 8(a) - the FIRST RUN on a machine, where `first_run_permission_setup`
launches all three for the TCC batch and the gate must still quit them - add
`--forget-permissions` to `--state cold`. That deletes the answered-prompts
record, so macOS will re-ask; someone has to be at the screen to click Allow.

The user documents are created by this script in a temp directory. Nothing of
the operator's is opened, edited or closed.
"""
from __future__ import annotations

import argparse
import json
import logging
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

# The exact verdicts `quit_idle_office_apps` logs, from applescript_bridge's own
# source. They are the difference between the two "left alone" reasons, and
# step 8 asks for the reason and not merely the outcome:
#   "we did not launch it"      -> observed, it was the user's
#   "we never drove it this run"-> never observed at all (the D11 hole)
LEFT_OBSERVED = "left alone (we did not launch it)"
LEFT_UNOBSERVED = "left alone (we never drove it this run)"


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


def _open_user_doc(app: str, work: Path, tag: str = "") -> Path | None:
    """A REAL document of the user's, opened and made dirty."""
    bundle, klass, ext, _key = APPS[app]
    src = _legacy_doc(work, f"user_{app}{tag}") if app == "Word" else \
        (_samples(ext, 1) or [None])[0]
    if src is None:
        return None
    doc = work / f"MY {app.upper()} WORK{tag}{src.suffix}"
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


class _LogGrab(logging.Handler):
    """The `[OfficeQuit]` lines, which are what step 8 actually asks you to read.

    The outcome alone cannot distinguish "left alone because it was yours" from
    "left alone because we never looked" - and the second was the bug. Only the
    log carries the reason.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(record.getMessage())
        except Exception:                       # noqa: BLE001
            pass

    def since(self, mark: int) -> list[str]:
        return [x for x in self.lines[mark:] if "[OfficeQuit]" in x]


class _Sink:
    def __getattr__(self, _n):
        return lambda *x, **k: None


def _stage_course(work: Path, name: str, apps: list[str], n: int):
    """A course folder, as a download would leave it."""
    course = work / name
    course.mkdir()
    staged, expect = [], {}
    for app in apps:
        _b, _k, ext, _key = APPS[app]
        srcs = [_legacy_doc(work, f"{name}{app}{i}") for i in range(n)] \
            if app == "Word" else _samples(ext, n)
        srcs = [s for s in srcs if s]
        for i, s in enumerate(srcs):
            d = course / f"{app} Lecture {i + 1}{s.suffix}"
            shutil.copy2(s, d)
            staged.append(d)
        expect[app] = len(srcs)
    return course, staged, expect


def _convert(course: Path, staged: list[Path], contract: dict):
    from core.sync_manager import SyncManager
    from converters.post_processing import run_all_conversions, UIBridge

    log: list = []
    ui = UIBridge(header_placeholder=_Sink(), progress_placeholder=_Sink(),
                  metrics_placeholder=_Sink(), log_placeholder=_Sink(),
                  active_file_placeholder=_Sink(), log_lines=log)
    sm = SyncManager(str(course), 43660, "Course")
    t0 = time.time()
    run_all_conversions(course, sm, contract, ui, course_name="Course",
                        explicit_files=[str(p) for p in staged])
    return ui, log, round(time.time() - t0, 1)


def _teardown(expect_quit: list[str]) -> float:
    """The app's own teardown - what the completion screen calls.

    It runs on a DAEMON THREAD and returns immediately, and the Recents purge is
    its LAST step: measured, it lands ~15s after the final process dies (wait-
    for-exit plus the retry pass). The first version of this script broke out as
    soon as `pgrep` was empty and then measured, which reported a working purge
    as broken. Wait for the teardown's own outcome instead, bounded.

    With nothing expected to quit (the busy/cancel shapes) the purge correctly
    declines - it is per-app and every app is running - so there is no settled
    state to wait for and the cap is short.
    """
    from engine.applescript_bridge import quit_idle_office_apps
    t = time.time()
    quit_idle_office_apps()
    cap = 90 if expect_quit else 30
    while time.time() - t < cap:
        quit_done = not any(_running(APPS[x][0]) for x in expect_quit)
        if quit_done and _recents_ours() <= 0:
            break
        time.sleep(1)
    return round(time.time() - t, 1)


def _one_run(course: Path, staged: list[Path], contract: dict,
             grab: _LogGrab, *, expect_quit: list[str]) -> dict:
    """One COMPLETE run, sequenced exactly as `app.py` sequences it.

    app.py:1386  reset_office_priming()          <- clears this run's Office state
    app.py:1397  first_run_permission_setup()    <- observes, then batches TCC
    app.py:1768  prime_office_automation()       <- per course; LAUNCHES the apps
                 run_all_conversions()
    app.py:2727  quit_idle_office_apps()         <- the teardown

    The first three are what this script used to skip.
    """
    from engine.applescript_bridge import (
        reset_office_priming, first_run_permission_setup, prime_office_automation,
    )
    mark = len(grab.lines)

    reset_office_priming()
    try:
        first_run_permission_setup(contract)
    except Exception as e:                      # noqa: BLE001
        print(f"  note: first_run_permission_setup raised: {e}", file=sys.stderr)
    prime_office_automation(contract)

    ui, log, convert_s = _convert(course, staged, contract)
    teardown_s = _teardown(expect_quit)

    plain = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(x))).strip() for x in log]
    return {
        "converted_ok": ui.pp_success_count,
        "failed": ui.pp_failure_count,
        "convert_seconds": convert_s,
        "teardown_seconds": teardown_s,
        "pdfs": sorted(p.name for p in course.glob("*.pdf")),
        "sources_left": sorted(p.name for p in course.glob("* Lecture *")
                               if p.suffix != ".pdf"),
        "office_quit_log": grab.since(mark),
        "errors": [x[:110] for x in plain if "fail" in x.lower()][:5],
    }


def _bad_pdfs(course: Path) -> list[str]:
    from converters.verify import pdf_looks_real
    return [p.name for p in course.glob("*.pdf") if not pdf_looks_real(p)[0]]


# ---------------------------------------------------------------- the states


def _state_single(a, apps: list[str], contract: dict, work: Path,
                  grab: _LogGrab) -> dict:
    """cold | busy - one run, from opposite starting states."""
    course, staged, expect = _stage_course(work, "Course", apps, a.files)

    _quit_all()
    user_docs = {}
    if a.state == "busy":
        for app in apps:
            user_docs[app] = _open_user_doc(app, work)
    before_docs = {app: _docs_open(app) for app in apps}
    before_recents = _recents_ours()

    expect_quit = [] if a.state == "busy" else apps
    run = _one_run(course, staged, contract, grab, expect_quit=expect_quit)

    per_app, problems = {}, []
    for app in apps:
        _b, _k, ext, _key = APPS[app]
        pdfs = sorted(p.name for p in course.glob(f"{app} Lecture*.pdf"))
        left = sorted(p.name for p in course.glob(f"{app} Lecture*{ext}"))
        still_open = _docs_open(app)
        per_app[app] = {
            "sources": expect[app], "pdfs": len(pdfs), "sources_left": left,
            "app_running_after": _running(APPS[app][0]),
            "docs_before": before_docs[app], "docs_after": still_open,
            "user_document_survived": None if a.state == "cold" else still_open >= 1,
        }
        r = per_app[app]
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

    bad = _bad_pdfs(course)
    after_recents = _recents_ours()
    if bad:
        problems.append(f"unusable PDFs: {bad}")
    if a.state == "cold" and after_recents > 0:
        problems.append(f"Recents still holds {after_recents} of our entries")

    return {
        "run": run, "per_app": per_app, "unusable_pdfs": bad,
        "recents_ours_before": before_recents, "recents_ours_after": after_recents,
        "user_documents": {k: str(v) for k, v in user_docs.items()},
        "problems": problems,
    }


def _state_two_runs(a, apps: list[str], contract: dict, work: Path,
                    grab: _LogGrab) -> dict:
    """MAC_RUNBOOK M1 step 8(b) - the data-loss path.

        run 1  nothing open -> download+convert -> all three quit
        then   open Word, type something, DO NOT SAVE, leave it open
        run 2  convert a second course, WITHOUT restarting the app

    Word must survive run 2 with its document intact, and run 2's log must read
    `left alone (we did not launch it)`. Before the fix the observation was per
    PROCESS, so run 2 answered with run 1's facts, called Word ours, and - the
    conversion phase having just made the documents undescribable - quit it
    `saving no`.
    """
    c1, s1, e1 = _stage_course(work, "Course1", apps, a.files)
    c2, s2, e2 = _stage_course(work, "Course2", apps, a.files)

    _quit_all()
    problems = []

    # ---- run 1: cold. Everything we launch must be quit again. -------------
    run1 = _one_run(c1, s1, contract, grab, expect_quit=apps)
    run1_running = {app: _running(APPS[app][0]) for app in apps}
    for app, up in run1_running.items():
        if up:
            problems.append(f"run 1: {app} left running with no user document")
    for app in apps:
        n = len(list(c1.glob(f"{app} Lecture*.pdf")))
        if n != e1[app]:
            problems.append(f"run 1: {app} {n}/{e1[app]} converted")

    # ---- between the runs: the user opens Word and does not save. ----------
    user_doc = _open_user_doc("Word", work, tag="_between")
    docs_between = _docs_open("Word")
    if docs_between < 1:
        problems.append("SETUP FAILED: could not open a user document in Word "
                        "between the runs - run 2 proves nothing")

    # ---- run 2: SAME PROCESS. Word is now the user's. ----------------------
    run2 = _one_run(c2, s2, contract, grab,
                    expect_quit=[x for x in apps if x != "Word"])
    word_running_after = _running("Microsoft Word")
    word_docs_after = _docs_open("Word")

    if not word_running_after:
        problems.append("THE USER'S WORD WAS QUIT BY RUN 2 - this is the D9/D11 "
                        "data loss")
    elif word_docs_after < 1:
        problems.append("Word survived but its document was closed - "
                        "`saving no` reached the user's unsaved work")
    for app in apps:
        n = len(list(c2.glob(f"{app} Lecture*.pdf")))
        if n != e2[app]:
            problems.append(f"run 2: {app} {n}/{e2[app]} converted")
    for app in apps:
        if app != "Word" and _running(APPS[app][0]):
            problems.append(f"run 2: {app} left running with no user document")

    # The REASON, not just the outcome. A stale "ours" that happened not to
    # quit Word would still pass every check above.
    verdicts = [x for x in run2["office_quit_log"] if "Microsoft Word ->" in x]
    if not any(LEFT_OBSERVED in x for x in verdicts):
        problems.append(
            f"run 2's verdict for Word is not {LEFT_OBSERVED!r} - got {verdicts}")

    return {
        "run1": run1, "run2": run2,
        "run1_apps_running_after": run1_running,
        "user_document": str(user_doc),
        "word_docs_between_runs": docs_between,
        "word_running_after_run2": word_running_after,
        "word_docs_after_run2": word_docs_after,
        "word_verdict_run2": verdicts,
        "unusable_pdfs": _bad_pdfs(c1) + _bad_pdfs(c2),
        "problems": problems,
    }


def _state_cancel(_a, _apps: list[str], _contract: dict, work: Path,
                  grab: _LogGrab) -> dict:
    """MAC_RUNBOOK M1 step 8(c) - cancelled before anything primed.

    Takes the same arguments as the other two states so `main` can dispatch
    uniformly; a cancelled run converts nothing, so most of them are unused.

    The teardown fires on the cancelled screens too (`cleanup_download_state` /
    `cleanup_sync_state` both call it), so it can run having observed NOTHING.
    An app in that state used to count as ours, because the lookup was
    `dict.get(app, False)`; absent is now a third answer meaning leave it.
    """
    _quit_all()
    user_doc = _open_user_doc("Word", work, tag="_cancel")
    docs_before = _docs_open("Word")
    problems = []
    if docs_before < 1:
        problems.append("SETUP FAILED: could not open a user document in Word - "
                        "this check proves nothing")

    from engine.applescript_bridge import reset_office_priming
    mark = len(grab.lines)
    # Run start clears the per-run observation; the user then cancels before
    # `prime_office_automation` (or even `first_run_permission_setup`) ever
    # looks at anything. Nothing is observed, and the teardown still fires.
    reset_office_priming()
    teardown_s = _teardown(expect_quit=[])

    running_after = _running("Microsoft Word")
    docs_after = _docs_open("Word")
    verdicts = [x for x in grab.since(mark) if "Microsoft Word ->" in x]

    if not running_after:
        problems.append("THE USER'S WORD WAS QUIT by a teardown that never "
                        "observed it")
    elif docs_after < 1:
        problems.append("Word survived but its document was closed")
    if not any(LEFT_UNOBSERVED in x for x in verdicts):
        problems.append(
            f"verdict is not {LEFT_UNOBSERVED!r} - got {verdicts}")

    return {
        "user_document": str(user_doc),
        "word_docs_before": docs_before,
        "word_running_after": running_after,
        "word_docs_after": docs_after,
        "word_verdict": verdicts,
        "teardown_seconds": teardown_s,
        "problems": problems,
    }


def main() -> int:
    if sys.platform != "darwin":
        print("macOS only", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", choices=("cold", "busy", "two-runs", "cancel"),
                    default="cold")
    ap.add_argument("--apps", action="append", choices=sorted(APPS))
    ap.add_argument("--files", type=int, default=3, help="per app")
    ap.add_argument("--forget-permissions", action="store_true",
                    help="delete the answered-Automation-prompts record first, "
                         "so this run is a FIRST run (step 8a). macOS will "
                         "re-ask - someone must be at the screen to click Allow.")
    a = ap.parse_args()
    apps = a.apps or ["Word", "Excel", "PowerPoint"]

    if a.state in ("two-runs", "cancel") and "Word" not in apps:
        # Both scenarios are about Word specifically: it is the app whose
        # documents D9 measured as undescribable after a conversion phase.
        apps = ["Word"] + apps

    grab = _LogGrab()
    blog = logging.getLogger("engine.applescript_bridge")
    blog.addHandler(grab)
    blog.setLevel(logging.INFO)

    forgot = None
    if a.forget_permissions:
        from engine.applescript_bridge import _permission_record_path
        p = _permission_record_path()
        if p.exists():
            p.unlink()
            forgot = str(p)
        print(f"forget-permissions: {forgot or 'no record existed'}",
              file=sys.stderr)

    work = Path(tempfile.mkdtemp(prefix="cd_e2e_"))
    contract = {APPS[app][3]: True for app in apps}

    if a.state in ("cold", "busy"):
        body = _state_single(a, apps, contract, work, grab)
    elif a.state == "two-runs":
        body = _state_two_runs(a, apps, contract, work, grab)
    else:
        body = _state_cancel(a, apps, contract, work, grab)

    problems = body.pop("problems")
    result = {"state": a.state, "apps": apps,
              "forgot_permission_record": forgot, **body,
              "problems": problems,
              "VERDICT": "ALL GOOD" if not problems else "PROBLEMS - see above"}
    print(json.dumps(result, indent=1, ensure_ascii=False, default=str))

    _quit_all()
    shutil.rmtree(work, ignore_errors=True)
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
