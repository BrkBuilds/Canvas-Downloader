"""The agent-facing command surface.

Every verb prints ONE JSON object to stdout and nothing else, so the agent never
has to parse prose and never has to write throwaway Python. That constraint is
the whole reason this file exists: an audit whose checks are re-invented per
invocation produces findings that cannot be compared between runs.

    python -m tests.audit --help
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

# Allow `python -m tests.audit` from the repo root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Windows consoles default to CP1252, and this suite handles Danish course names,
# emoji-bearing filenames and the app's own arrow glyphs on every screen. Without
# this, printing a perfectly-good extraction dies with UnicodeEncodeError and the
# failure looks like a harness bug rather than a console setting. 'replace' on
# stderr so a traceback can always be shown even if it contains something exotic.
for _stream, _errors in ((sys.stdout, "strict"), (sys.stderr, "replace")):
    try:
        _stream.reconfigure(encoding="utf-8", errors=_errors)
    except (AttributeError, ValueError):
        pass

from tests.audit.harness import appctl, browser, paths  # noqa: E402


def _out(obj) -> int:
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")
    return 0


def _err(msg: str, **extra) -> int:
    sys.stdout.write(json.dumps({"ok": False, "error": msg, **extra},
                                indent=2, ensure_ascii=False, default=str) + "\n")
    return 1


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m tests.audit",
        description="Canvas Downloader live audit harness.")
    ap.add_argument("--run", help="Run id to act on (default: the current run)")
    sub = ap.add_subparsers(dest="group", required=True)

    # -- run -------------------------------------------------------------
    g = sub.add_parser("run", help="Audit run directories").add_subparsers(
        dest="cmd", required=True)
    p = g.add_parser("new", help="Create a run directory with isolated app state")
    p.add_argument("--label", default="")
    g.add_parser("list", help="List runs")
    p = g.add_parser("use", help="Make a run current")
    p.add_argument("run_id")
    g.add_parser("info", help="Paths and metadata for the current run")

    # -- app -------------------------------------------------------------
    g = sub.add_parser("app", help="The application under test").add_subparsers(
        dest="cmd", required=True)
    p = g.add_parser("start")
    p.add_argument("--port", type=int)
    g.add_parser("stop")
    g.add_parser("status")
    g.add_parser("restart")

    # -- browser ---------------------------------------------------------
    g = sub.add_parser("browser", help="The persistent browser").add_subparsers(
        dest="cmd", required=True)
    p = g.add_parser("open")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--port", type=int,
                   help="pin the CDP port instead of scanning for a free one. "
                        "The scan tests liveness and binds a moment later, so "
                        "it races anything else starting at the same time - "
                        "pin it whenever a parallel run is already going.")
    g.add_parser("close")
    p = g.add_parser("goto", help="Navigate; blank url = app home")
    p.add_argument("--mode", default="")
    p.add_argument("--step", default="")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--url", default="")

    # -- ui --------------------------------------------------------------
    g = sub.add_parser("ui", help="Drive and read the screen").add_subparsers(
        dest="cmd", required=True)
    p = g.add_parser("capture", help="Screenshot + structured extraction")
    p.add_argument("name")
    p.add_argument("--what", default="screen",
                   help="comma list of screen,wizard,dashboard,review,completion,today")
    p.add_argument("--viewport", action="store_true", help="viewport-only screenshot")
    p = g.add_parser("click")
    p.add_argument("key")
    p.add_argument("--force", action="store_true",
                   help="click even when the app has painted it unavailable")
    p.add_argument("--no-settle", action="store_true")
    p = g.add_parser("check", help="Set a checkbox/toggle to an explicit state")
    p.add_argument("key")
    p.add_argument("value", choices=["on", "off"])
    p = g.add_parser("fill")
    p.add_argument("key")
    p.add_argument("text")
    p = g.add_parser("expand")
    p.add_argument("key")
    p.add_argument("--close", action="store_true")
    p = g.add_parser("probe", help="Inspect one control without touching it")
    p.add_argument("key")
    p.add_argument("--role", default="button", choices=["button", "checkbox", "input"])
    p = g.add_parser("extract")
    p.add_argument("what", choices=["screen", "wizard", "dashboard", "review",
                                    "completion", "today"])
    p = g.add_parser("wait", help="Poll until a named phase condition holds")
    p.add_argument("condition")
    p.add_argument("--timeout", type=float, default=3600.0)
    p.add_argument("--poll", type=float, default=3.0)
    g.add_parser("settle", help="Block until the DOM stops changing")
    p = g.add_parser("scroll")
    p.add_argument("to", choices=["top", "bottom"])
    p = g.add_parser("press", help="Send a key to the page (Escape closes a dialog)")
    p.add_argument("key", help="Playwright key name, e.g. Escape, Enter, Tab")

    # -- flows -----------------------------------------------------------
    g = sub.add_parser("flow", help="Drive a whole user flow end to end"
                       ).add_subparsers(dest="cmd", required=True)
    p = g.add_parser("download", help="Select -> configure -> download -> capture")
    p.add_argument("name", help="scenario name; prefixes every capture")
    p.add_argument("--courses", required=True, help="comma list of course ids")
    p.add_argument("--config", default="{}", help="JSON config, or @file.json")
    p.add_argument("--timeout", type=float, default=5400.0)
    p = g.add_parser("quick-download")
    p.add_argument("name")
    p.add_argument("--courses", required=True)
    p.add_argument("--timeout", type=float, default=5400.0)
    p = g.add_parser("sync", help="Analyze (+review) -> confirm -> capture")
    p.add_argument("name")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--no-confirm", action="store_true",
                   help="stop at the review screen without syncing")
    p.add_argument("--select", default="",
                   help="comma list of review categories to TICK before syncing "
                        "(e.g. updated_modified,deleted_locally). Those two are "
                        "unchecked by default, so without this the _NewVersion "
                        "and restore paths are never exercised.")
    p.add_argument("--timeout", type=float, default=5400.0)
    p = g.add_parser("today")
    p.add_argument("name")
    p.add_argument("--quick-sync", action="store_true")
    p.add_argument("--timeout", type=float, default=3600.0)

    # -- oracles ---------------------------------------------------------
    g = sub.add_parser("canvas", help="Oracle O5 - independent Canvas enumeration"
                       ).add_subparsers(dest="cmd", required=True)
    p = g.add_parser("snapshot")
    p.add_argument("course_id", type=int)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--full", action="store_true", help="print the whole snapshot")
    g.add_parser("courses", help="List active courses with ids and codes")

    g = sub.add_parser("disk", help="Oracle O3 - folder inventory").add_subparsers(
        dest="cmd", required=True)
    p = g.add_parser("scan")
    p.add_argument("folder")
    p.add_argument("--save", help="label to store this scan under for later diffing")
    p.add_argument("--no-hash", action="store_true")
    p.add_argument("--full", action="store_true")
    p = g.add_parser("diff")
    p.add_argument("before")
    p.add_argument("after")

    g = sub.add_parser("db", help="Oracle O4 - the sync manifest").add_subparsers(
        dest="cmd", required=True)
    p = g.add_parser("read")
    p.add_argument("folder")
    p.add_argument("--full", action="store_true")
    p = g.add_parser("reconcile", help="manifest vs disk")
    p.add_argument("folder")

    g = sub.add_parser("log", help="Oracle O2 - the debug log").add_subparsers(
        dest="cmd", required=True)
    p = g.add_parser("parse")
    p.add_argument("path", nargs="?", help="default: the run's batch debug_log.txt")
    p.add_argument("--full", action="store_true")

    # -- seeding ---------------------------------------------------------
    g = sub.add_parser("seed", help="Fabricate sync scenarios in a course folder"
                       ).add_subparsers(dest="cmd", required=True)
    p = g.add_parser("apply")
    p.add_argument("--again", action="store_true",
                   help="seed a folder that is already seeded (layers fixtures "
                        "on fixtures and invalidates both plans - restore a "
                        "snapshot instead)")
    p.add_argument("folder")
    p.add_argument("--kinds", default="", help="comma list; default = all")
    p.add_argument("--counts", default="", help="kind=N,kind=N")
    g.add_parser("kinds", help="List available fixture kinds")
    p = g.add_parser("unlock", help="Undo read-only fixtures so cleanup can run")
    p.add_argument("folder")

    # -- matrix ----------------------------------------------------------
    g = sub.add_parser("matrix", help="Combinatorial run plan").add_subparsers(
        dest="cmd", required=True)
    p = g.add_parser("build")
    p.add_argument("--no-triple", action="store_true")
    p.add_argument("--courses", default="", help="comma list of course ids to assign across")
    p.add_argument("--kind", default="download", choices=["download", "sync"],
                   help="download = the config space; sync = the WORLD space "
                        "(what changed, and how the user accepts it) replayed "
                        "against frozen folders")
    p.add_argument("--snapshots", default="",
                   help="sync only: comma list of snapshot names to assign "
                        "across (default: every captured snapshot)")
    p.add_argument("--save", action="store_true")
    p.add_argument("--full", action="store_true")
    g.add_parser("show", help="The saved plan for this run")
    p = g.add_parser("prepare", help="Split the saved plan into parallel lanes")
    p.add_argument("--lanes", type=int, default=4)
    p.add_argument("--kind", default="download", choices=["download", "sync"])
    p.add_argument("--headed", action="store_true",
                   help="Show each lane's browser (default: headless)")
    p.add_argument("--jobs", default="", help="@file.json of explicit jobs "
                                              "instead of the saved matrix plan")
    p.add_argument("--app-base", type=int,
                   help="move the whole app port band (default 8800). Use when "
                        "another matrix is still running.")
    p.add_argument("--cdp-base", type=int, help="likewise for CDP (default 9400)")
    p = g.add_parser("launch", help="Start the lane workers")
    p.add_argument("--no-wait", action="store_true")
    g.add_parser("lanes", help="Progress across all lanes")
    g.add_parser("recheck", help="Re-derive every lane's findings from its "
                                 "saved evidence with the CURRENT checker")
    p = g.add_parser("collect", help="Merge lane findings into this run")
    p.add_argument("--rechecked", action="store_true",
                   help="merge what `recheck` re-derived instead of what the "
                        "workers wrote as they ran (use whenever the checker "
                        "changed mid-run)")
    p = g.add_parser("worker", help="(internal) execute one lane's jobs")

    # -- snapshots --------------------------------------------------------
    g = sub.add_parser(
        "snapshot", help="Golden copies of downloaded course folders"
    ).add_subparsers(dest="cmd", required=True)
    p = g.add_parser("capture", help="Freeze a downloaded folder for reuse")
    p.add_argument("folder")
    p.add_argument("--name", default="", help="default: c<course_id>_base")
    p.add_argument("--course-id", type=int, default=0)
    p.add_argument("--course-name", default="")
    p.add_argument("--note", default="")
    p.add_argument("--config", default="", help="JSON, or @file.json")
    p.add_argument("--deep", action="store_true", help="md5 every file")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--allow-seeded", action="store_true",
                   help="capture a folder that already carries audit fixtures "
                        "(deliberately a mid-scenario baseline, not a clean one)")
    p = g.add_parser("restore", help="Materialise a snapshot into this run")
    p.add_argument("name")
    p.add_argument("--into", default="", help="default: the run's downloads dir")
    p.add_argument("--as", dest="as_name", default="", help="rename the folder")
    p.add_argument("--pair", action="store_true", help="also register the sync pair")
    g.add_parser("list")
    p = g.add_parser("verify")
    p.add_argument("name")
    p.add_argument("folder")
    p = g.add_parser("drop")
    p.add_argument("name")

    # -- checks / findings / report --------------------------------------
    g = sub.add_parser("check", help="Run a crosscheck suite and record findings"
                       ).add_subparsers(dest="cmd", required=True)
    p = g.add_parser("invariants")
    p.add_argument("folder")
    p.add_argument("--capture", default="", help="UI capture name to include")
    p.add_argument("--log", default="", help="debug log path; default = the folder's")
    p = g.add_parser("download")
    p.add_argument("folder")
    p.add_argument("--course-id", type=int, required=True)
    p.add_argument("--expect", required=True, help="JSON config, or @file.json")
    p.add_argument("--capture", default="")
    p.add_argument("--scenario", default="")
    # Download mode writes ONE batch log at the download root, not a per-course
    # one, so this check must be pointed at it explicitly. Defaults to the run's
    # batch log rather than the folder's, which is the sync-mode location.
    p.add_argument("--log", default="", help="debug log path (default: batch log)")
    p = g.add_parser("sync")
    p.add_argument("folder")
    p.add_argument("--plan", required=True, help="seed plan JSON path")
    p.add_argument("--capture", default="", help="review capture name")
    p.add_argument("--after", default="", help="disk scan label taken AFTER the sync")
    p.add_argument("--before", default="", help="disk scan label taken BEFORE it; "
                                                "enables the 'untouched' checks")
    p.add_argument("--scenario", default="")
    p.add_argument("--log", default="", help="debug log path (default: the folder's)")

    g = sub.add_parser("finding", help="Record a judgment finding the agent made"
                       ).add_subparsers(dest="cmd", required=True)
    p = g.add_parser("add")
    p.add_argument("title")
    p.add_argument("--severity", default="medium",
                   choices=["critical", "high", "medium", "low", "info"])
    p.add_argument("--category", default="ui-truth")
    p.add_argument("--oracles", default="O1")
    p.add_argument("--detail", default="")
    p.add_argument("--evidence", default="", help="JSON, or @file.json")
    p.add_argument("--scenario", default="")
    p.add_argument("--course", default="")
    p.add_argument("--step", default="")
    p.add_argument("--synthetic", action="store_true")
    p = g.add_parser("list")
    p.add_argument("--limit", type=int, default=40)
    p = g.add_parser("classes", help="Fold findings into classes, and diff two "
                                     "sets of them - the triage view for a matrix")
    p.add_argument("--source", default="rechecked",
                   choices=["rechecked", "as-run", "merged"],
                   help="which ledger to read: the lanes' re-derived findings "
                        "(default), the lanes' as-run findings, or this run's "
                        "own merged findings.jsonl")
    p.add_argument("--against", default="",
                   choices=["", "rechecked", "as-run"],
                   help="diff --source against this one, BY CLASS. With no "
                        "product change between them, everything it lists is "
                        "the checker")
    p.add_argument("--defects-only", action="store_true",
                   help="drop info/observation rows")
    p.add_argument("--limit", type=int, default=40)

    g = sub.add_parser("report", help="Render the HTML report").add_subparsers(
        dest="cmd", required=True)
    g.add_parser("build")
    g.add_parser("summary")

    g = sub.add_parser(
        "pair", help="Sync pairs (folder <-> course) in the run's isolated state"
    ).add_subparsers(dest="cmd", required=True)
    p = g.add_parser("add", help="Register a pair without the native folder picker")
    p.add_argument("folder")
    p.add_argument("--course-id", type=int, required=True)
    p.add_argument("--course-name", default="")
    p = g.add_parser("today", help="Put a pair in the daily-sync set")
    p.add_argument("folder")
    p.add_argument("--course-id", type=int, required=True)
    p.add_argument("--course-name", default="")
    p.add_argument("--remove", action="store_true")
    p.add_argument("--auto-sync", choices=["on", "off"])
    g.add_parser("list")

    g = sub.add_parser(
        "register",
        help="The cumulative, hand-editable findings register (tests/audit/AUDIT_FINDINGS.md)"
    ).add_subparsers(dest="cmd", required=True)
    g.add_parser("update", help="Merge this run's findings; preserves your statuses")
    g.add_parser("show", help="Status tally without writing anything")

    return ap


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return _dispatch(args)
    except SystemExit:
        raise
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", traceback=traceback.format_exc()[-2500:])


def _dispatch(args) -> int:
    g, c = args.group, getattr(args, "cmd", None)

    if g == "run":
        if c == "new":
            rp = paths.new_run(args.label)
            return _out({"ok": True, **rp.as_dict()})
        if c == "list":
            return _out({"ok": True, "runs": paths.list_runs()})
        if c == "use":
            return _out({"ok": True, **paths.use_run(args.run_id).as_dict()})
        if c == "info":
            rp = paths.resolve(args.run)
            return _out({"ok": True, **rp.as_dict(), "meta": rp.load_meta()})

    rp = paths.resolve(args.run)

    if g == "app":
        if c == "start":
            return _out({"ok": True, **appctl.start(rp, args.port)})
        if c == "stop":
            return _out({"ok": True, **appctl.stop(rp)})
        if c == "status":
            return _out({"ok": True, **appctl.status(rp)})
        if c == "restart":
            appctl.stop(rp)
            return _out({"ok": True, **appctl.start(rp)})

    if g == "browser":
        if c == "open":
            return _out({"ok": True, **browser.open_browser(
                rp, headed=not args.headless, port=args.port)})
        if c == "close":
            return _out({"ok": True, **browser.close_browser(rp)})
        if c == "goto":
            with browser.session(rp) as s:
                url = args.url or s.app_url(args.mode, args.step, args.quick)
                res = s.goto(url)
                return _out({"ok": True, "url": url, "ready": res})

    if g == "ui":
        return _ui(rp, args)
    if g == "flow":
        return _flow(rp, args)
    if g in ("canvas", "disk", "db", "log", "seed", "matrix", "check",
             "finding", "report", "register", "pair", "snapshot"):
        return _data(rp, args)

    return _err(f"Unhandled command: {g} {c}")


# --------------------------------------------------------------------------

def _load_json_arg(v: str):
    """Accept inline JSON or @path, so a large config never hits the shell."""
    if not v:
        return {}
    if v.startswith("@"):
        return json.loads(Path(v[1:]).read_text(encoding="utf-8"))
    return json.loads(v)


def _scan_path(rp, label: str) -> Path:
    return Path(rp.evidence) / f"disk_{label}.json"


def _snapshot_metas(names=None) -> dict:
    """Snapshot metadata by name, skipping anything not usable as a baseline.

    A snapshot captured from a folder a previous scenario had already seeded is
    stored with `MIDSCENARIO` in its name precisely so it is never picked up by
    accident: seeding on top of it produces categories no plan can predict.
    """
    from tests.audit.harness import snapshot as snap
    if names is None:
        names = [s["name"] for s in snap.list_snapshots()
                 if not s.get("broken") and "MIDSCENARIO" not in s["name"]]
    out = {}
    for name in names:
        try:
            out[name] = snap.read_meta(name)
        except Exception:
            continue
    return out


def _tally(items) -> dict:
    out: dict = {}
    for i in items:
        out[str(i)] = out.get(str(i), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _tally_courses(runs: list) -> dict:
    """Rows per course, so a lopsided plan is visible before it is launched.

    Counts every course a row selects, not just its first: a row covering
    {panopto, zip} downloads both, and a tally that saw only the primary would
    under-report the expensive one by design.
    """
    out: dict[str, int] = {}
    for r in runs:
        for cid in (r.get("_course_ids") or [r.get("_course_id")]):
            k = str(cid)
            out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


_DIGEST_KEYS = ("ok", "landed_on", "capture", "captures", "drift", "failed",
                "terminal", "expanded", "consoleErrors", "exceptions",
                "category", "touched", "want")


def _digest(v):
    """Summarise one flow step for the console.

    Handles a LIST of steps as well as a single one: ``--select`` performs one
    per category, and assuming a dict here crashed the whole command AFTER the
    sync had already run and been traced - so the work was done and the result
    unreadable.
    """
    if isinstance(v, list):
        return [_digest(x) for x in v]
    if isinstance(v, dict):
        return {k: val for k, val in v.items() if k in _DIGEST_KEYS}
    return v


def _flow(rp, args) -> int:
    """Run a whole user flow. Long-running by design - a real download of a
    real course - so it always writes its trace, even on failure."""
    from tests.audit.harness import browser as B
    from tests.audit.harness import flows

    c = args.cmd
    with B.session(rp) as s:
        try:
            if c == "download":
                f = flows.DownloadFlow(s, rp)
                ids = [int(x) for x in args.courses.split(",") if x.strip()]
                res = f.run(args.name, ids, _load_json_arg(args.config))
            elif c == "quick-download":
                f = flows.DownloadFlow(s, rp)
                ids = [int(x) for x in args.courses.split(",") if x.strip()]
                res = {"name": args.name, "select": f.select_courses(ids),
                       "open": f.open_quick()}
                s.capture(f"{args.name}_quick_config", ("screen",))
                res["run"] = f.confirm_and_run(args.name, timeout=args.timeout)
                res["trace"] = f.trace
            elif c == "sync":
                f = flows.SyncFlow(s, rp)
                res = {"name": args.name, "open": f.open()}
                res["analyze"] = f.analyze(args.name, quick=args.quick,
                                           timeout=args.timeout)
                if res["analyze"].get("landed_on") == "review":
                    res["review"] = f.review_snapshot(f"{args.name}_review")
                    # Ticking happens AFTER the first capture so the evidence
                    # records the screen's own defaults, then again after so the
                    # outcome checks see what was actually selected.
                    sel = [x.strip() for x in args.select.split(",") if x.strip()]
                    if sel:
                        res["select"] = [f.select_category(c2) for c2 in sel]
                        res["review"] = f.review_snapshot(f"{args.name}_review")
                if not args.no_confirm:
                    res["confirm"] = f.confirm(args.name, timeout=args.timeout)
                res["trace"] = f.trace
            elif c == "today":
                f = flows.TodayFlow(s, rp)
                res = {"name": args.name, "open": f.open()}
                if args.quick_sync:
                    res["sync"] = f.quick_sync(f"{args.name}_after", timeout=args.timeout)
                res["trace"] = f.trace
            else:
                return _err(f"Unknown flow '{c}'")
        except Exception as e:
            trace_path = flows.save_trace(rp, args.name,
                                          {"error": f"{type(e).__name__}: {e}",
                                           "traceback": traceback.format_exc()[-3000:]})
            try:
                s.capture(f"{args.name}_FAILED", ("screen", "wizard"))
            except Exception:
                pass
            return _err(f"{type(e).__name__}: {e}", trace=trace_path,
                        capture=f"{args.name}_FAILED")

    path = flows.save_trace(rp, args.name, res)
    # Record what ran so the report can show scope without re-deriving it.
    meta = rp.load_meta()
    scope = meta.get("scope", [])
    scope.append({"name": args.name, "flow": c,
                  "course": getattr(args, "courses", ""),
                  "config": json.dumps(_load_json_arg(getattr(args, "config", "{}")),
                                       ensure_ascii=False)[:300],
                  "result": "ok" if (res.get("run", res.get("confirm", {}))
                                     .get("ok", True)) else "INCOMPLETE"})
    rp.update_meta(scope=scope)

    digest = {"ok": True, "name": args.name, "trace": path}
    for k in ("select", "open", "configure", "run", "analyze", "review",
              "confirm", "sync"):
        if k in res:
            digest[k] = _digest(res[k])
    return _out(digest)


def _data(rp, args) -> int:
    from tests.audit.harness import crosscheck, matrix, report, seed as seeder
    from tests.audit.harness.findings import Finding, Ledger
    from tests.audit.harness.oracles import canvas as ocanvas
    from tests.audit.harness.oracles import db as odb
    from tests.audit.harness.oracles import disk as odisk
    from tests.audit.harness.oracles import log as olog

    g, c = args.group, args.cmd

    # -- O5 ---------------------------------------------------------------
    if g == "canvas":
        if c == "courses":
            return _out({"ok": True, "courses": ocanvas.list_courses()})
        snap = ocanvas.snapshot(args.course_id, rp.canvas, refresh=args.refresh)
        return _out({"ok": True, **(snap if args.full else ocanvas.brief(snap))})

    # -- O3 ---------------------------------------------------------------
    if g == "disk":
        if c == "scan":
            res = odisk.scan(args.folder, full_hash=not args.no_hash)
            saved = None
            if args.save:
                saved = odisk.save(res, _scan_path(rp, args.save))
            return _out({"ok": True, "saved": saved,
                         **(res if args.full else odisk.brief(res))})
        if c == "diff":
            before = odisk.load(_scan_path(rp, args.before))
            after = odisk.load(_scan_path(rp, args.after))
            return _out({"ok": True, **odisk.diff(before, after)})

    # -- O4 ---------------------------------------------------------------
    if g == "db":
        info = odb.read(args.folder)
        if c == "read":
            return _out({"ok": True, **(info if args.full else odb.brief(info))})
        if c == "reconcile":
            d = odisk.scan(args.folder, full_hash=True)
            return _out({"ok": True, **odb.reconcile_with_disk(info, d)})

    # -- O2 ---------------------------------------------------------------
    if g == "log":
        path = args.path or str(rp.batch_debug_log())
        parsed = olog.parse(path)
        s = olog.summarize(parsed)
        if not args.full:
            s.pop("sync_planned", None)
            s.pop("analysis_rows", None)
        return _out({"ok": True, **s})

    # -- seeding ----------------------------------------------------------
    if g == "seed":
        if c == "kinds":
            return _out({"ok": True, "kinds": list(seeder.Seeder.ALL)})
        if c == "apply":
            kinds = [k.strip() for k in args.kinds.split(",") if k.strip()] or None
            counts = {}
            for pair in filter(None, (p.strip() for p in args.counts.split(","))):
                k, _, v = pair.partition("=")
                counts[k] = int(v)
            plan = seeder.seed(args.folder, kinds, counts,
                               out_path=Path(rp.evidence) /
                               f"seed_{Path(args.folder).name}.json",
                               again=args.again)
            plan.pop("fixtures", None)
            return _out({"ok": True, **plan})
        if c == "unlock":
            p = Path(rp.evidence) / f"seed_{Path(args.folder).name}.json"
            plan = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
            return _out({"ok": True, "restored": seeder.restore_permissions(args.folder, plan)})

    # -- snapshots --------------------------------------------------------
    if g == "snapshot":
        from tests.audit.harness import snapshot as snap
        if c == "list":
            return _out({"ok": True, "root": str(snap.SNAPSHOT_ROOT),
                         "snapshots": snap.list_snapshots()})
        if c == "capture":
            folder = Path(args.folder)
            cid = args.course_id or (odb.read(folder).get("course_id") or 0)
            name = args.name or snap.auto_name(int(cid or 0))
            return _out({"ok": True, **snap.capture(
                folder, name, course_id=int(cid or 0) or None,
                course_name=args.course_name, config=_load_json_arg(args.config),
                note=args.note, deep=args.deep, overwrite=args.overwrite,
                allow_seeded=args.allow_seeded)})
        if c == "restore":
            into = Path(args.into) if args.into else rp.downloads
            res = snap.restore(args.name, into, folder_name=args.as_name)
            if args.pair:
                meta = snap.read_meta(args.name)
                if meta.get("course_id"):
                    res["pair"] = paths.add_sync_pair(
                        rp, res["path"], int(meta["course_id"]),
                        meta.get("course_name", ""))
            return _out({"ok": res.get("verify", {}).get("ok", True), **res})
        if c == "verify":
            return _out({"ok": True, **snap.verify_restore(args.name, args.folder)})
        if c == "drop":
            return _out({"ok": True, **snap.drop(args.name)})

    # -- matrix -----------------------------------------------------------
    if g == "matrix":
        # The two plans measure different spaces and must not overwrite each
        # other: a `prepare --kind sync` that silently read the download plan
        # would run 73 config rows as sync jobs with no snapshot and no seed.
        def _plan_path(kind: str) -> Path:
            return Path(rp.evidence) / ("matrix_plan.json" if kind == "download"
                                        else f"matrix_plan_{kind}.json")

        plan_path = _plan_path(getattr(args, "kind", "download"))
        if c in ("prepare", "launch", "lanes", "collect", "recheck", "worker"):
            from tests.audit.harness import parallel
            if c == "worker":
                return _out({"ok": True, **parallel.run_lane(rp)})
            if c == "prepare":
                if args.jobs:
                    jobs = [parallel.Job(**j) for j in _load_json_arg(args.jobs)]
                else:
                    if not plan_path.is_file():
                        return _err(f"No {args.kind} matrix plan saved yet; run: "
                                    f"matrix build --kind {args.kind} ... --save")
                    plan = json.loads(plan_path.read_text(encoding="utf-8"))
                    if args.kind == "sync":
                        jobs = parallel.sync_jobs_from_plan(
                            plan, _snapshot_metas(plan.get("snapshots")))
                    else:
                        jobs = parallel.jobs_from_plan(plan, kind=args.kind)
                return _out({"ok": True, **parallel.prepare(
                    rp, jobs, lanes=args.lanes, headless=not args.headed,
                    app_base=args.app_base, cdp_base=args.cdp_base)})
            if c == "launch":
                return _out({"ok": True, **parallel.launch(rp, wait=not args.no_wait)})
            if c == "lanes":
                return _out({"ok": True, **parallel.status(rp)})
            if c == "recheck":
                return _out({"ok": True, **parallel.recheck(rp)})
            if c == "collect":
                return _out({"ok": True, **parallel.collect(
                    rp, rechecked=args.rechecked)})
        if c == "show":
            if not plan_path.is_file():
                return _err(f"No {getattr(args, 'kind', 'download')} matrix plan "
                            f"saved yet; run: matrix build --save")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan.pop("runs", None)
            return _out({"ok": True, **plan})

        if args.kind == "sync":
            plan = matrix.sync_plan(triple=not args.no_triple)
            names = [x.strip() for x in args.snapshots.split(",") if x.strip()]
            metas = _snapshot_metas(names or None)
            plan["snapshots"] = sorted(metas)
            from tests.audit.harness import parallel as _par
            plan["snapshot_capabilities"] = {
                n: sorted(_par.snapshot_capabilities(m)) for n, m in metas.items()}
            jobs = _par.sync_jobs_from_plan(plan, metas)
            plan["assignment"] = _tally(j.snapshot for j in jobs)
            if args.save:
                plan_path.write_text(matrix.to_json(plan), encoding="utf-8")
                plan["saved"] = str(plan_path)
            if not args.full:
                plan.pop("factors", None)
                plan["runs"] = len(plan["runs"])
            return _out({"ok": True, **plan})

        plan = matrix.build_plan(triple=not args.no_triple)
        if args.courses:
            caps, stats = {}, {}
            for cid in (int(x) for x in args.courses.split(",") if x.strip()):
                snap = ocanvas.snapshot(cid, rp.canvas)
                caps[cid] = matrix.capabilities(snap)
                stats[cid] = matrix.course_stats(snap)
            plan = matrix.assign_courses(plan, caps, stats=stats)
            plan["capabilities"] = {str(k): sorted(v) for k, v in caps.items()}
            plan["course_stats"] = {str(k): v for k, v in stats.items()}
            plan["assignment"] = _tally_courses(plan["runs"])
        if args.save:
            plan_path.write_text(matrix.to_json(plan), encoding="utf-8")
            plan["saved"] = str(plan_path)
        if not args.full:
            plan.pop("factors", None)
            plan["runs"] = len(plan["runs"])
        return _out({"ok": True, **plan})

    # -- checks -----------------------------------------------------------
    if g == "check":
        ledger = Ledger(rp.findings)
        folder = Path(args.folder)
        # A check is a MEASUREMENT of this folder, re-derived every run, so a
        # second pass supersedes the first instead of stacking on top of it.
        # Without this, re-checking after a repair left the pre-repair
        # findings in the ledger and the register reported the repair as
        # still broken - three times, each cleaned up by hand.
        _origin = f"{c}@{os.path.normcase(str(folder.resolve()))}"
        ui = {}
        if getattr(args, "capture", ""):
            up = Path(rp.ui) / f"{args.capture}.json"
            if up.is_file():
                ui = json.loads(up.read_text(encoding="utf-8"))

        d = odisk.scan(folder, full_hash=True)
        info = odb.read(folder)
        # Sync writes a per-course log inside the folder; download writes one
        # batch log at the download root. Prefer whichever the check is about,
        # then fall back, so neither suite silently reads an empty log and
        # reports a clean run because it looked in the wrong place.
        log_path = getattr(args, "log", "")
        if not log_path:
            candidates = ([str(rp.batch_debug_log()), str(folder / "debug_log.txt")]
                          if c == "download"
                          else [str(folder / "debug_log.txt"), str(rp.batch_debug_log())])
            log_path = next((p for p in candidates if Path(p).is_file()), candidates[0])
        lg = olog.parse_and_summarize(log_path)

        if c == "invariants":
            ev = crosscheck.Evidence(folder=folder, disk=d, db=info, log=lg, ui=ui,
                                     scenario=getattr(args, "scenario", ""))
            found = ledger.extend(crosscheck.invariants(ev), origin=_origin)
        elif c == "download":
            expect = _load_json_arg(args.expect)
            snap = ocanvas.snapshot(args.course_id, rp.canvas)
            ev = crosscheck.Evidence(folder=folder, disk=d, db=info, log=lg, ui=ui,
                                     canvas=snap, expect=expect,
                                     scenario=args.scenario)
            found = ledger.extend(crosscheck.invariants(ev) +
                                  crosscheck.download_run(ev), origin=_origin)
        elif c == "sync":
            plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
            # Outcome checks ("was this file restored / left alone / forked to
            # _NewVersion") only mean anything once a sync has actually run.
            # Without --after they were compared against the PRE-sync folder, so
            # every 'restored' fixture reported as missing - 13 fabricated
            # criticals on a run that deliberately stopped at the review screen.
            after = (odisk.load(_scan_path(rp, args.after))
                     if args.after and _scan_path(rp, args.after).is_file() else None)
            # The "untouched" assertions need the pre-sync bytes to compare
            # against; without --before they are skipped rather than guessed.
            before = (odisk.load(_scan_path(rp, args.before))
                      if args.before and _scan_path(rp, args.before).is_file() else None)
            # Derived rather than read straight from the plan so a plan written
            # before these declarations existed gets them too, and so there is
            # one definition of "the seeder broke this on purpose".
            ev = crosscheck.Evidence(
                folder=folder, disk=d, db=info, log=lg, ui=ui,
                expect={"expected_untracked": plan.get("expected_untracked", []),
                        **seeder.declarations(plan.get("fixtures", []))},
                scenario=args.scenario)
            found = ledger.extend(
                crosscheck.invariants(ev) +
                crosscheck.sync_run(ev, plan, ui.get("review"), after, before),
                origin=_origin)
        else:
            return _err(f"Unknown check '{c}'")

        return _out({"ok": True, "suite": c, "new_findings": len(found),
                     "by_severity": _tally(f.severity for f in found),
                     "titles": [f"[{f.severity}] {f.title}" for f in found[:25]],
                     "summary": ledger.summary()})

    # -- findings / report -------------------------------------------------
    if g == "finding":
        ledger = Ledger(rp.findings)
        if c == "add":
            f = Finding(title=args.title, severity=args.severity,
                        category=args.category,
                        oracles=tuple(o.strip() for o in args.oracles.split(",") if o.strip()),
                        detail=args.detail, evidence=_load_json_arg(args.evidence),
                        scenario=args.scenario, course=args.course, step=args.step,
                        synthetic=args.synthetic)
            ledger.add(f)
            return _out({"ok": True, "recorded": f.as_dict(),
                         "summary": ledger.summary()})
        if c == "list":
            return _out({"ok": True, "summary": ledger.summary(),
                         "findings": ledger.ranked(args.limit)})
        if c == "classes":
            from tests.audit.harness import classes as fclasses

            info = not args.defects_only

            def _read(which: str):
                # "merged" is this run's own ledger; the other two are the
                # LANES'. A matrix parent's findings.jsonl holds only what was
                # collected into it (and anything added by hand), so reading it
                # for a run whose lanes have not been collected yet reports
                # near-zero - which reads as a clean run rather than an
                # uncollected one.
                if which == "merged":
                    return [dict(f, lane=f.get("lane")) for f in ledger.all()], []
                return fclasses.collect_lanes(Path(rp.root),
                                              rechecked=(which == "rechecked"))

            rows, missing = _read(args.source)
            # Both numbers, always. `findings` alone is ambiguous next to a
            # `--defects-only` class list - it is the total INCLUDING info, so
            # printing it beside 7 defect classes reads as "374 defects".
            defects = [f for f in rows if f.get("severity") != "info"
                       and f.get("category") != "observation"]
            sev: dict = {}
            for f in defects:
                sev[f.get("severity", "medium")] = sev.get(f.get("severity", "medium"), 0) + 1
            out = {"ok": True, "run": rp.run_id, "source": args.source,
                   "findings": len(rows), "defects": len(defects),
                   "by_severity": sev,
                   "blocking": sev.get("critical", 0) + sev.get("high", 0)}
            if missing:
                out["missing_lanes"] = missing
            if args.against:
                other, other_missing = _read(args.against)
                out["against"] = args.against
                out["diff"] = fclasses.diff(other, rows, include_info=info)
                if other_missing:
                    out["missing_lanes_against"] = other_missing
            else:
                grouped = fclasses.annotate_with_register(
                    fclasses.group(rows, include_info=info))
                out["classes"] = len(grouped)
                # The first question of triage, answered up front: how much of
                # this is genuinely new? A matrix run days long can end with
                # every surviving class already fixed in the tree, and reading
                # the raw list gives no hint of that.
                tally: dict = {}
                for r in grouped:
                    tally[r["register"]] = tally.get(r["register"], 0) + 1
                out["by_register"] = tally
                out["by_class"] = grouped[:args.limit]
            return _out(out)

    if g == "pair":
        # Written directly into the run's isolated state, in the app's own
        # persisted format. Not a shortcut for convenience: "Add Course" opens
        # the OS folder picker (shared.helpers.pick_folder -> tkinter/osascript),
        # which is a native dialog Playwright cannot drive at all. The picker
        # itself therefore needs manual verification and is recorded as a
        # coverage gap; everything downstream of a registered pair - which is
        # the whole of sync - is exercised normally.
        # The writers live in harness.paths, next to provision_config_dir, so the
        # parallel workers register pairs through the same code rather than a
        # second implementation of the same on-disk format.
        if c == "list":
            return _out({"ok": True,
                         "pairs": paths._read_json(
                             Path(rp.config) / "canvas_sync_pairs.json", []),
                         "today": paths._read_json(
                             Path(rp.config) / "today_dashboard.json",
                             {"auto_sync_enabled": False, "pairs": []})})
        if c == "add":
            return _out({"ok": True, **paths.add_sync_pair(
                rp, args.folder, args.course_id, args.course_name)})
        if c == "today":
            auto = None if not args.auto_sync else (args.auto_sync == "on")
            return _out({"ok": True, **paths.set_today_pair(
                rp, args.folder, args.course_id, args.course_name,
                remove=args.remove, auto_sync=auto)})

    if g == "register":
        from tests.audit.harness import register as reg
        if c == "update":
            return _out({"ok": True, **reg.update_from_run(rp)})
        if c == "show":
            entries = reg.parse()
            return _out({"ok": True, "register": str(reg.REGISTER_PATH),
                         "total": len(entries),
                         "by_status": _tally(e["status"] for e in entries.values()),
                         "open": [f"[{e['severity']}] {e['title']}"
                                  for e in entries.values() if e["status"] == "open"]})

    if g == "report":
        if c == "build":
            extra = {}
            mp = Path(rp.evidence) / "matrix_plan.json"
            if mp.is_file():
                plan = json.loads(mp.read_text(encoding="utf-8"))
                extra["coverage"] = plan.get("coverage_2way")
            extra["scope"] = rp.load_meta().get("scope", [])
            path = report.build(rp, extra)
            return _out({"ok": True, "report": path, **report.console(rp)})
        if c == "summary":
            return _out({"ok": True, **report.console(rp)})

    return _err(f"Unhandled command: {g} {c}")


def _tally(items) -> dict:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def _ui(rp, args) -> int:
    from tests.audit.harness import conditions

    c = args.cmd
    with browser.session(rp) as s:
        if c == "capture":
            what = tuple(w.strip() for w in args.what.split(",") if w.strip())
            return _out({"ok": True, **s.capture(args.name, what,
                                                 full_page=not args.viewport)})
        if c == "click":
            return _out({"ok": True, **s.click(args.key, settle=not args.no_settle,
                                               force_gated=args.force)})
        if c == "check":
            return _out({"ok": True, **s.set_checkbox(args.key, args.value == "on")})
        if c == "fill":
            return _out({"ok": True, **s.fill(args.key, args.text)})
        if c == "expand":
            return _out({"ok": True, **s.expand(args.key, open_=not args.close)})
        if c == "probe":
            return _out({"ok": True, **s.probe_key(args.key, args.role)})
        if c == "extract":
            return _out({"ok": True, args.what: s.extract(args.what)})
        if c == "settle":
            return _out({"ok": True, **s.settle()})
        if c == "scroll":
            s.scroll_main(args.to)
            return _out({"ok": True, "scrolled": args.to})
        if c == "press":
            return _out({"ok": True, **s.press(args.key)})
        if c == "wait":
            js = conditions.get(args.condition)
            if js is None:
                return _err(f"Unknown condition '{args.condition}'",
                            available=conditions.names())
            return _out({"ok": True, "condition": args.condition,
                         **s.wait_for(js, timeout=args.timeout, poll=args.poll,
                                      label=args.condition)})
    return _err(f"Unhandled ui command: {c}")


if __name__ == "__main__":
    raise SystemExit(main())
