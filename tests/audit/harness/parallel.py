"""Run the matrix in parallel lanes, with the things that cannot share serialised.

The matrix is ~73 rows and a row is minutes to an hour, so it is the part of the
audit that decides whether the suite is something you run or something you mean
to run. Four lanes is roughly a working day instead of most of a week.

Parallelism here is only safe because each lane is a genuinely separate
application: its own ``CANVAS_DL_CONFIG_DIR`` (so pairs, history, groups,
presets and the Today list cannot bleed between lanes), its own Streamlit port,
its own Chrome and browser profile, and its own download root. That isolation
already existed for a single run - a lane is just another run directory, which
means every existing CLI command works against a lane unchanged.

**Two resources cannot be shared, and they set the lane classes.**

``office`` - Word, Excel and PowerPoint conversion drive Office through Win32
COM. ``win32com.client.Dispatch`` attaches to the machine-wide Application
object, so two lanes converting at once are two threads steering ONE Excel:
documents open in the wrong instance, ``Workbooks.Open`` returns somebody else's
workbook, and the failure mode is a hang rather than an exception. These rows
all run in one lane, in sequence.

``gpu`` - transcription. The GPU is one device, ctranslate2 is not re-entrant
across processes competing for it, and this project already carries a scar from
an OpenMP clash that segfaults rather than erroring (which is why
``panopto/transcribe_worker.py`` exists at all). Same treatment: one lane.

Everything else is ``free`` and spreads across the remaining lanes.

The scheduler is deliberately static - rows are partitioned up front, not pulled
from a shared queue. A queue would balance better, but a lane's assignment would
then depend on timing, and a run list that reshuffles between invocations cannot
be compared against its own history. That is the same reason the covering array
is generated deterministically.

Progress is recorded per row, so an interrupted audit resumes instead of
restarting. A twelve-hour suite that cannot resume is a suite that never
finishes once anything goes wrong.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .paths import (REPO_ROOT, RunPaths, add_sync_pair, app_env,
                    provision_config_dir, remove_sync_pair)

# Port bands. Disjoint by construction: a "find a free port" probe races with
# itself when several lanes start together, and on Windows the SO_REUSEADDR
# behaviour that makes such probes wrong is already documented in start.py.
APP_PORT_BASE = 8800
CDP_PORT_BASE = 9400
PORT_STRIDE = 10

OFFICE_FACTORS = ("convert_word", "convert_excel", "convert_pptx")
GPU_FACTORS = ("pan_out_txt", "pan_out_srt")

LANE_CLASSES = ("office", "gpu", "free")


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------

@dataclass
class Job:
    """One matrix row, all the way through to its checks."""
    id: str
    kind: str                      # "download" | "sync"
    course_id: int
    config: dict = field(default_factory=dict)
    name: str = ""
    # Download rows may need several courses to exercise every factor they
    # switch on - see matrix.assign_courses. Empty means "just course_id",
    # which keeps every hand-written job spec working unchanged.
    course_ids: list = field(default_factory=list)
    # sync jobs only. ``seed_kinds`` is tri-state on purpose: ``None`` means
    # every fixture, an EMPTY LIST means none of them. "Nothing changed" is a
    # scenario in its own right - it is what puts the empty-analysis screen
    # under test - and collapsing it into "seed everything" produced the
    # loudest possible folder checked against an expectation of total quiet.
    snapshot: str = ""
    seed_kinds: list | None = None
    seed_counts: dict = field(default_factory=dict)
    quick: bool = False
    confirm: bool = True
    note: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = self.id
        self.course_ids = [int(c) for c in (self.course_ids or [self.course_id])]
        self.course_id = self.course_ids[0]

    @property
    def lane_class(self) -> str:
        return classify(self.config)


def classify(config: dict) -> str:
    """Which shared resource a row needs exclusive use of."""
    if any(config.get(f) for f in GPU_FACTORS):
        return "gpu"
    if any(config.get(f) for f in OFFICE_FACTORS):
        return "office"
    return "free"


def jobs_from_plan(plan: dict, *, kind: str = "download",
                   prefix: str = "m") -> list[Job]:
    """Turn a saved matrix plan into jobs, preserving the plan's own order.

    An unassigned row is an ERROR, never a skip. This used to ``continue`` past
    it, so the one row no course could satisfy (``dl_syllabus``) vanished
    between "73 runs, 100% coverage" and the 72 jobs that actually ran - a
    coverage hole with nothing anywhere to report it. ``assign_courses`` now
    always assigns; if that ever regresses, this stops the run instead of
    quietly shrinking it.
    """
    out = []
    for i, row in enumerate(plan.get("runs", [])):
        cfg = {k: v for k, v in row.items() if not k.startswith("_")}
        cid = row.get("_course_id")
        if cid is None:
            raise SystemExit(
                f"matrix row {i} ({row.get('_isolates') or 'pairwise'}) has no "
                f"course assigned - rebuild the plan with: matrix build "
                f"--courses ... --save")
        out.append(Job(id=f"{prefix}{i:03d}", kind=kind, course_id=int(cid),
                       course_ids=[int(x) for x in
                                   (row.get("_course_ids") or [cid])],
                       config=cfg, note=row.get("_isolates", "")))
    return out


def snapshot_capabilities(meta: dict) -> set[str]:
    """What a frozen folder can exercise, from the contract it was built with.

    A sync run's configuration is not chosen at sync time - it is the CONTRACT
    the folder carries, so the snapshot is the configuration. A fixture that
    needs Canvas Content cannot be seeded into a folder downloaded without it,
    and a run against one would report "0 new secondary" as a defect.
    """
    caps: set[str] = set()
    cfg = meta.get("config") or {}
    if any(v for k, v in cfg.items() if k.startswith("dl_")):
        caps.add("secondary")
    if any(v for k, v in cfg.items() if k.startswith("convert_")):
        caps.add("converted")
    if cfg.get("convert_zip"):
        caps.add("archives")
    inv = meta.get("inventory") or {}
    if any(len(p) > 180 for p in inv):
        caps.add("long_path")
    # ENOUGH MATERIAL TO SEED. Almost every fixture works by picking a tracked
    # file and doing something to it - renaming it, editing it, moving it,
    # copying it - and the seeder simply reports "no eligible candidate in this
    # folder" when it cannot find one. That is silent: the row runs, seeds
    # nothing, analyses nothing and passes. Measured while building the sync
    # plan: with cost as the only tie-break, 34 of 43 rows were assigned to a
    # 2-file, 1-row snapshot that could not have exercised a single one of them.
    rows = (meta.get("manifest") or {}).get("rows") or meta.get("manifest_rows") or 0
    if int(rows) >= _MIN_SEED_ROWS:
        caps.add("material")
    return caps


# The seeder needs several distinct candidates per kind (renamed_ambiguous
# alone wants two that could plausibly be the same file), and a run turns over
# a handful per fixture. Twenty tracked rows is the smallest folder where every
# kind has somewhere to land.
_MIN_SEED_ROWS = 20


def sync_jobs_from_plan(plan: dict, snapshots: dict[str, dict], *,
                        prefix: str = "s") -> list[Job]:
    """Turn a sync plan into jobs, each bound to ONE frozen folder.

    Unlike a download row, a sync row cannot spread across several courses:
    it syncs one pair, so it gets one snapshot. Selection is the same
    capability-first, cost-second rule - a snapshot that cannot exercise the
    row's fixtures produces a green result that proves nothing.
    """
    from .matrix import SEED_KINDS, SYNC_FACTORS

    if not snapshots:
        raise SystemExit("sync jobs need at least one snapshot; capture one "
                         "with: snapshot capture <folder> --name <n>")
    req = {f.name: f.requires for f in SYNC_FACTORS if f.requires}
    caps = {n: snapshot_capabilities(m) for n, m in snapshots.items()}
    cost = {n: float(m.get("files") or 0) for n, m in snapshots.items()}

    out = []
    for i, row in enumerate(plan.get("runs", [])):
        wanted = {req[k] for k, v in row.items() if k in req and v}
        # Every snapshot that can exercise this row, best capability first.
        ranked = sorted(sorted(snapshots),
                        key=lambda n: (-len(wanted & caps[n]), cost[n], n))
        # SPREAD across INTERCHANGEABLE snapshots instead of always taking the
        # cheapest. The contract a folder carries - flat vs modules, isolated
        # secondary, the study filter - is a sync input in its own right: it
        # decides where a new file belongs, and whether a filtered-out file may
        # come back as "new". Nothing in the plan asks for a shape by name, so
        # left to cost alone every row went to one snapshot and the other
        # shapes, each of which cost a full download to capture, were never
        # synced at all.
        #
        # Interchangeable means the SAME capability set, not merely the same
        # number of matches: a row that needs nothing in particular matches a
        # 1-row folder and a 21,822-file one equally, and spreading across
        # those two is not coverage, it is 26 seconds of restore for nothing.
        # Round-robin by row index, so the plan stays deterministic.
        group = [n for n in ranked if caps[n] == caps[ranked[0]]]
        best = group[i % len(group)]
        kinds = [k for k in SEED_KINDS if row.get(k)]
        out.append(Job(
            id=f"{prefix}{i:03d}", kind="sync",
            course_id=int(snapshots[best].get("course_id") or 0),
            snapshot=best, seed_kinds=kinds,
            quick=(row.get("sync_mode") == "quick"),
            confirm=bool(row.get("confirm", True)),
            note=row.get("_isolates", ""),
            config={"sync_mode": row.get("sync_mode"),
                    "confirm": row.get("confirm", True)}))
    return out


# --------------------------------------------------------------------------
# partitioning
# --------------------------------------------------------------------------

def partition(jobs: list[Job], lanes: int = 4) -> list[dict]:
    """Split jobs into lanes, giving office and gpu their own serial lane.

    A class only gets a lane if it has work: reserving an office lane for a run
    list with no Office rows would waste a quarter of the machine, and the
    common case of "re-run just the converter rows" would then have one lane
    doing everything and three idle.
    """
    if lanes < 1:
        raise ValueError("lanes must be >= 1")

    by_class: dict[str, list[Job]] = {c: [] for c in LANE_CLASSES}
    for j in jobs:
        by_class[j.lane_class].append(j)

    serial = [c for c in ("office", "gpu") if by_class[c]]
    # Never spend every lane on the serial classes - free work would then never
    # start, and free rows are usually the bulk of the list.
    serial = serial[:max(0, lanes - 1)] if by_class["free"] else serial[:lanes]

    out: list[dict] = []
    for c in serial:
        out.append({"lane": c, "serial": True, "jobs": by_class[c]})
    # A serial class that did not get its own lane still must not run in
    # parallel with itself, so it is appended to whichever lane already
    # serialises - never scattered across the free ones.
    for c in ("office", "gpu"):
        if by_class[c] and c not in serial:
            (out[0]["jobs"] if out else by_class["free"]).extend(by_class[c])

    free_lanes = max(1, lanes - len(out)) if by_class["free"] else 0
    for i in range(free_lanes):
        out.append({"lane": f"free{i + 1}", "serial": False, "jobs": []})
    if by_class["free"]:
        free_slots = [d for d in out if not d["serial"]]
        for i, j in enumerate(by_class["free"]):
            free_slots[i % len(free_slots)]["jobs"].append(j)

    out = [d for d in out if d["jobs"]]
    for i, d in enumerate(out):
        d["index"] = i
        d["app_port"] = APP_PORT_BASE + i * PORT_STRIDE
        d["cdp_port"] = CDP_PORT_BASE + i * PORT_STRIDE
        d["count"] = len(d["jobs"])
        # A single lane is serial whatever it holds, and saying otherwise would
        # be a lie in the one arrangement where the office/gpu rule is being
        # honoured by having nothing to run alongside.
        d["serial"] = d["serial"] or len(out) == 1
    return out


# --------------------------------------------------------------------------
# launching
# --------------------------------------------------------------------------

def lane_run_id(parent_run_id: str, lane: str) -> str:
    return f"{parent_run_id}__{lane}"


def prepare(parent: RunPaths, jobs: list[Job], lanes: int = 4,
            headless: bool = True, app_base: int | None = None,
            cdp_base: int | None = None) -> dict:
    """Write each lane's spec and provision its isolated run directory.

    ``app_base``/``cdp_base`` move the whole port band. Needed whenever another
    matrix is still running: the default band is fixed, so a second `prepare`
    hands lane 2 the port lane 2 of the first run is already serving, and the
    worker dies with "served by another process" - correctly, but only after
    everything else has been provisioned.
    """
    parts = partition(jobs, lanes)
    specs = []
    for d in parts:
        rid = lane_run_id(parent.run_id, d["lane"])
        lrp = RunPaths(rid).create()
        provision_config_dir(lrp)
        lrp.update_meta(run_id=rid, label=f"lane:{d['lane']}",
                        parent=parent.run_id, lane=d["lane"],
                        created=datetime.now().isoformat(timespec="seconds"))
        app_port = ((app_base + d["index"] * PORT_STRIDE)
                    if app_base else d["app_port"])
        cdp_port = ((cdp_base + d["index"] * PORT_STRIDE)
                    if cdp_base else d["cdp_port"])
        spec = {
            "lane": d["lane"], "index": d["index"], "serial": d["serial"],
            "parent": parent.run_id, "run_id": rid,
            "app_port": app_port, "cdp_port": cdp_port,
            "headless": headless,
            "jobs": [asdict(j) for j in d["jobs"]],
        }
        spec_path = lrp.root / "lane_spec.json"
        spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False),
                             encoding="utf-8")
        d["app_port"], d["cdp_port"] = app_port, cdp_port
        specs.append({**{k: v for k, v in spec.items() if k != "jobs"},
                      "count": len(d["jobs"]), "spec": str(spec_path)})

    plan_path = parent.root / "lanes.json"
    plan_path.write_text(json.dumps({"parent": parent.run_id, "lanes": specs},
                                    indent=2, ensure_ascii=False), encoding="utf-8")
    return {"parent": parent.run_id, "lanes": specs, "plan": str(plan_path),
            "total_jobs": sum(s["count"] for s in specs)}


def _live_workers(plan: dict) -> list[dict]:
    """Lane workers from a previous launch that are still running.

    Identified by the lane's own run id appearing in a live `matrix worker`
    command line - the run id is unique per lane, so this cannot collide with an
    unrelated matrix on the same machine. Best-effort: if `ps` is unavailable the
    answer is "none", because a launch that cannot check must still be possible.
    """
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,command="], capture_output=True,
                             text=True, timeout=30).stdout or ""
    except Exception:                                           # noqa: BLE001
        return []
    live: list[dict] = []
    me = os.getpid()
    for lane in plan.get("lanes", []):
        rid = lane.get("run_id") or ""
        if not rid:
            continue
        # The CONTIGUOUS argv form, not three tokens found anywhere on the line.
        # A loose match reports the checking process itself: any script whose
        # source merely mentions the run id, "matrix" and "worker" - including
        # this guard's own test - satisfies the loose form and the launcher then
        # refuses to start for no reason.
        needle = f"--run {rid} matrix worker"
        for line in out.splitlines():
            line = line.strip()
            if needle not in line:
                continue
            pid = line.split(None, 1)[0]
            if pid.isdigit() and int(pid) != me:
                live.append({"lane": lane.get("lane"), "pid": int(pid),
                             "run_id": rid})
            break
    return live


def launch(parent: RunPaths, *, wait: bool = True, poll: float = 20.0,
           startup_grace: float = 12.0) -> dict:
    """Spawn one worker process per lane and (optionally) wait for them all."""
    plan_path = parent.root / "lanes.json"
    if not plan_path.is_file():
        raise SystemExit("No lane plan. Run: matrix parallel prepare ...")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    # A SECOND launch over a live one is silently destructive, so refuse it.
    # Measured 2026-08-10: launching twice (the first call printed nothing and
    # looked like it had failed) started a second set of workers that could not
    # bind the lane ports, exited, and ran their `finally` - which calls
    # appctl.stop() and close_browser() on the SAME lane run dirs the first set
    # was using. The live lanes lost their apps mid-job, _recover cycled them,
    # and four completed rows failed for a reason that had nothing to do with
    # the product. `--app-base` exists for a deliberate concurrent matrix; this
    # is the accident it does not cover.
    alive = _live_workers(plan)
    if alive:
        raise SystemExit(
            "A matrix is already running for this run: "
            + ", ".join(f"{a['lane']} (pid {a['pid']})" for a in alive)
            + ".\nWatch it with `matrix lanes`, or kill those pids first. "
              "To run a SECOND matrix on purpose, prepare it with "
              "--app-base/--cdp-base so the two cannot share ports.")

    procs = []
    for lane in plan["lanes"]:
        rid = lane["run_id"]
        lrp = RunPaths(rid)
        log = lrp.root / "worker.log"
        # ``--run`` is a TOP-LEVEL option, declared before add_subparsers, so it
        # has to precede the subcommand: `matrix worker --run X` exits with
        # "unrecognized arguments" before the worker starts. Every lane would
        # have died in its first second, and the only trace is a line in a
        # per-lane worker.log nobody reads until the run looks finished.
        cmd = [sys.executable, "-m", "tests.audit", "--run", rid,
               "matrix", "worker"]
        with open(log, "ab") as lf:
            lf.write(f"\n=== lane {lane['lane']} start "
                     f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode())
            p = subprocess.Popen(
                cmd, cwd=str(REPO_ROOT), env=app_env(lrp), stdout=lf, stderr=lf,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        procs.append({"lane": lane["lane"], "run_id": rid, "pid": p.pid,
                      "proc": p, "log": str(log)})

    # A lane that dies on startup is INVISIBLE otherwise: `lanes` reports
    # 0-of-N done, which is also what a healthy lane looks like for its first
    # ten minutes, and `collect` then merges nothing and reports success. Give
    # the workers a moment and check they are still alive, quoting whatever
    # they managed to say. A bad argv cost exactly this once.
    time.sleep(startup_grace)
    dead = []
    for d in procs:
        # A NON-ZERO exit inside the grace window is a lane that died on
        # startup. A ZERO exit is a lane with nothing left to do - on a resumed
        # run every one of its rows is already complete, so it finishes in
        # under a second. Treating that as death reported a finished lane as
        # broken AND terminated its still-working siblings.
        if d["proc"].poll() not in (None, 0):
            tail = ""
            try:
                tail = Path(d["log"]).read_text(encoding="utf-8",
                                                errors="replace")[-800:]
            except OSError:
                pass
            dead.append({"lane": d["lane"], "run_id": d["run_id"],
                         "returncode": d["proc"].returncode, "log_tail": tail})

    parent.update_meta(lanes=[{k: v for k, v in d.items() if k != "proc"}
                              for d in procs])
    if dead:
        for d in procs:
            if d["proc"].poll() is None:
                d["proc"].terminate()
        raise SystemExit(json.dumps(
            {"error": f"{len(dead)} lane worker(s) exited immediately",
             "dead": dead}, indent=2, ensure_ascii=False))

    if not wait:
        return {"status": "launched",
                "lanes": [{k: v for k, v in d.items() if k != "proc"} for d in procs]}

    while any(d["proc"].poll() is None for d in procs):
        time.sleep(poll)
    return {"status": "finished",
            "lanes": [{"lane": d["lane"], "run_id": d["run_id"],
                       "returncode": d["proc"].returncode,
                       **progress(RunPaths(d["run_id"]))} for d in procs]}


def status(parent: RunPaths) -> dict:
    plan_path = parent.root / "lanes.json"
    if not plan_path.is_file():
        return {"status": "no-plan"}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    lanes = []
    for lane in plan["lanes"]:
        lrp = RunPaths(lane["run_id"])
        lanes.append({"lane": lane["lane"], "run_id": lane["run_id"],
                      "planned": lane["count"], **progress(lrp)})
    done = sum(l.get("done", 0) for l in lanes)
    total = sum(l.get("planned", 0) for l in lanes)
    return {"parent": parent.run_id, "done": done, "total": total,
            "percent": round(100.0 * done / total, 1) if total else 0.0,
            "lanes": lanes}


# --------------------------------------------------------------------------
# progress (resumability)
# --------------------------------------------------------------------------

def _progress_path(rp: RunPaths) -> Path:
    return rp.root / "progress.json"


def progress(rp: RunPaths) -> dict:
    p = _progress_path(rp)
    if not p.is_file():
        return {"done": 0, "failed": 0, "rows": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"done": 0, "failed": 0, "rows": []}
    # A row's state is its LATEST attempt. `_record` appends, and a resumed run
    # re-runs exactly the rows that failed - so after a successful retry the
    # file holds both records, and counting them all reports the row as still
    # failed for the rest of the run, while `done` climbs past the number of
    # rows there are. The append-only history is deliberate (it shows what was
    # retried); collapsing it belongs here, at the point of reporting.
    latest: dict[str, dict] = {}
    for r in data.get("rows", []):
        if r.get("id"):
            latest[r["id"]] = r
    rows = list(latest.values())
    return {"done": len(rows),
            "failed": sum(1 for r in rows if not r.get("ok")),
            "retried": sum(1 for r in rows if r.get("id") in
                           {x.get("id") for x in data.get("rows", [])
                            if not x.get("ok")} and r.get("ok")),
            "current": data.get("current", ""),
            "rows": [r["id"] for r in rows][-8:]}


def _record(rp: RunPaths, row: dict) -> None:
    p = _progress_path(rp)
    data = {"rows": []}
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    data.setdefault("rows", []).append(row)
    data["current"] = ""
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                 encoding="utf-8")


def _mark_current(rp: RunPaths, job_id: str) -> None:
    p = _progress_path(rp)
    data = {"rows": []}
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["current"] = job_id
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                 encoding="utf-8")


def _completed(rp: RunPaths) -> set[str]:
    p = _progress_path(rp)
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return set()
    # Only successful rows are skipped on resume. A row that failed is exactly
    # the one worth trying again, and a row abandoned mid-flight (the process
    # was killed) never got a record at all.
    return {r["id"] for r in data.get("rows", []) if r.get("ok")}


# --------------------------------------------------------------------------
# the worker
# --------------------------------------------------------------------------

def run_lane(rp: RunPaths) -> dict:
    """Execute this lane's jobs in order. Called in the worker process."""
    from . import appctl, browser, snapshot as snap

    spec_path = rp.root / "lane_spec.json"
    if not spec_path.is_file():
        raise SystemExit(f"No lane_spec.json in {rp.root}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    jobs = [Job(**j) for j in spec["jobs"]]
    done = _completed(rp)

    appctl.start(rp, port=spec["app_port"])
    browser.open_browser(rp, headed=not spec.get("headless", True),
                         port=spec["cdp_port"])

    results = []
    try:
        for job in jobs:
            if job.id in done:
                results.append({"id": job.id, "ok": True, "skipped": "already done"})
                continue
            _mark_current(rp, job.id)
            t0 = time.time()
            try:
                res = execute(rp, job)
                res.update({"id": job.id, "seconds": round(time.time() - t0, 1)})
            except Exception as e:
                import traceback
                res = {"id": job.id, "ok": False,
                       "error": f"{type(e).__name__}: {e}",
                       "traceback": traceback.format_exc()[-2000:],
                       "seconds": round(time.time() - t0, 1)}
                # A crashed row can leave the app mid-screen; the next row must
                # not inherit it, or one failure cascades into a whole lane of
                # false results.
                _recover(rp, appctl, browser, spec)
            _record(rp, res)
            results.append(res)
    finally:
        browser.close_browser(rp)
        appctl.stop(rp)

    return {"lane": spec["lane"], "run_id": rp.run_id, "jobs": len(jobs),
            "ok": sum(1 for r in results if r.get("ok")),
            "failed": [r["id"] for r in results if not r.get("ok")],
            "results": results}


def _recover(rp: RunPaths, appctl, browser, spec: dict) -> None:
    try:
        browser.close_browser(rp)
    except Exception:
        pass
    try:
        appctl.stop(rp)
    except Exception:
        pass
    try:
        appctl.start(rp, port=spec["app_port"])
    except Exception:
        pass
    # Reopen the browser with retries. The Chrome just killed by close_browser can
    # hold its CDP port and profile lock for a moment, so a single reopen races it
    # and fails - and a failed reopen leaves the lane with NO browser, so every
    # later row dies "Browser is not open". That turns one row's failure into a
    # whole lane of false failures, which is the exact opposite of what recovery
    # is for. Retry until the port/lock clears.
    for _attempt in range(5):
        try:
            browser.open_browser(rp, headed=not spec.get("headless", True),
                                 port=spec["cdp_port"])
            return
        except Exception:
            time.sleep(3)


def execute(rp: RunPaths, job: Job) -> dict:
    """One job, end to end: drive the UI, then cross-check what it produced."""
    if job.kind == "download":
        return _execute_download(rp, job)
    if job.kind == "sync":
        return _execute_sync(rp, job)
    raise SystemExit(f"Unknown job kind: {job.kind!r}")


def _execute_download(rp: RunPaths, job: Job) -> dict:
    from . import browser as B
    from . import crosscheck, flows
    from .findings import Ledger
    from .oracles import canvas as ocanvas
    from .oracles import db as odb
    from .oracles import disk as odisk
    from .oracles import log as olog

    # A row must start from nothing. The engine skips an existing file whose
    # size already matches (canvas_logic.py, "Skipping existing file"), so a
    # leftover folder for one of these courses would turn that course into a
    # no-op that still reports success - and a lane runs dozens of rows against
    # the same handful of courses.
    pruned = [p for p in (_prune_course_folder(rp, c) for c in job.course_ids) if p]
    offset = _log_size(rp.batch_debug_log())

    with B.session(rp) as s:
        f = flows.DownloadFlow(s, rp)
        res = f.run(job.name, list(job.course_ids), job.config)
    flows.save_trace(rp, job.name, res)

    # ONE UI capture for the row - the completion screen reports the whole
    # batch and has no per-course form. The disk, manifest, Canvas AND log
    # oracles are all per-course: see _log_for_course for why the log has to be
    # split too.
    row_log = _log_slice(rp, job.id, offset)
    ui = _ui_capture(rp, f"{job.name}_complete")
    ledger = Ledger(rp.findings)

    _expect, _unapplied = expect_for(rp, job)

    per_course, found, missing = [], [], []
    for cid in job.course_ids:
        folder = _course_folder(rp, cid)
        if folder is None:
            missing.append(cid)
            continue
        label = job.id if len(job.course_ids) == 1 else f"{job.id}_c{cid}"
        disk = odisk.scan(folder, full_hash=True)
        odisk.save(disk, Path(rp.evidence) / f"disk_{label}.json")
        log = olog.parse_and_summarize(_log_for_course(
            row_log, cid, Path(rp.logs) / f"{label}_course.txt"))
        ev = crosscheck.Evidence(
            folder=folder, disk=disk, db=odb.read(folder), log=log, ui=ui,
            canvas=ocanvas.snapshot(cid, rp.canvas),
            # The row's WHOLE log, for the phases that are batch-level and
            # cannot be split per course - Panopto downloads and transcribes
            # every course's recordings together, and its size-gate lines name
            # a recording title rather than a course. Checks read `log` first
            # and fall back to this; see _panopto_delivery.
            batch_log=_row_log_summary(olog, row_log),
            expect=_expect, scenario=label)
        got = ledger.extend(crosscheck.invariants(ev) + crosscheck.download_run(ev)
                            + _unapplied_note(_unapplied, label, cid))
        found.extend(got)
        per_course.append({"course_id": cid, "folder": str(folder),
                           "findings": len(got),
                           "harvest": _harvest_and_prune(rp, label, folder)})

    if missing:
        return {"ok": False, "reason": "no course folder was produced",
                "missing_courses": missing, "pruned_before": pruned,
                "course_ids": job.course_ids, "findings": len(found),
                "configure": res.get("configure", {}).get("ok")}

    return {"ok": bool(res.get("run", {}).get("ok")) and
            bool(res.get("configure", {}).get("ok")),
            "kind": "download", "course_id": job.course_id,
            "course_ids": job.course_ids, "courses": per_course,
            "findings": len(found),
            "drift": res.get("configure", {}).get("drift", []),
            "severities": _tally(x.severity for x in found)}


# Fixture kind -> the review category it lands in, for the categories the
# screen leaves UNCHECKED by default. "You have edited these" and "deleted
# locally" are unticked on purpose - the app will not overwrite your work or
# resurrect a file you removed without being asked - so a run that does not
# tick them exercises neither the _NewVersion path nor a restore, and the
# primary action stays DISABLED. Measured: the sync smoke row seeding
# `edited_update` timed out clicking a button that read `<button disabled>`.
_UNCHECKED_BY_DEFAULT = {
    "edited_update": "updated_modified",
    "deleted_locally": "deleted_locally",
    "readonly_target": "updated_modified",
}


def _categories_to_tick(seed_kinds) -> list[str]:
    """Review categories this row must select to exercise what it seeded."""
    out = []
    for kind in (seed_kinds or []):
        cat = _UNCHECKED_BY_DEFAULT.get(kind)
        if cat and cat not in out:
            out.append(cat)
    return out


# Every list a seed plan publishes about the state it deliberately created.
# `crosscheck.invariants` already knows how to suppress each one and keys off
# exactly these names - they are the contract between the seeder and the
# checker, and it is one-sided: a name added to the plan and not here is
# suppression the checker will never see.
_SEED_EXPECTATION_KEYS = ("expected_untracked", "expected_md5_drift",
                          "expected_size_drift", "expected_missing_rows",
                          "expected_partials")


def _sync_outcome_disk(job: "Job", after: dict | None) -> dict | None:
    """The after-scan, but ONLY when a sync actually ran.

    `crosscheck.sync_run`'s outcome checks ask "was this restored / left alone
    / forked to _NewVersion". Against a folder that stopped at the REVIEW
    screen every one of them is a fabricated failure, because nothing was
    supposed to happen to it yet. Passing None disables them.

    A function rather than an inline `if` at each site: the live row had it and
    the re-check had lost it, which put 26 invented criticals on a run whose
    live pass reported none.
    """
    return after if job.confirm else None


def seed_expectations(plan: dict) -> dict:
    """The plan's expectation lists, as `Evidence(expect=...)` wants them.

    ONE function because both places that build a sync Evidence need it - the
    live row and the re-check - and they had drifted to passing
    `expected_untracked` alone. That left the suppression machinery unfed, so
    the suite reported the harness's OWN fixtures as defects: measured on the
    43-row plan, 40 findings per run (12 "manifest row records the wrong size",
    9 "differ from their recorded md5", 6 "partial-write artifact left on
    disk", 4 "row points at a file that does not exist") whose paths matched
    the seed plan's lists ITEM FOR ITEM.

    Noise on that scale does not merely annoy - it is where a real finding
    hides. The one genuine critical in the pre-fix sync run sat among 90 of
    them.

    Each list is the UNION of what the plan stored and what its fixture list
    derives now - which is what `seed.declarations` is for ("Derived here
    rather than written only at seed time so an existing plan gets the same
    treatment"). Union rather than preference, because the failure being fixed
    was an INCOMPLETE stored list, not a missing one: `expected_untracked` was
    present on every plan and simply did not name the renames. Preferring the
    stored value would have left every plan written before today reporting the
    seeder's own renames as orphans for ever.
    """
    from . import seed as seeder
    try:
        derived = seeder.declarations(plan.get("fixtures") or [])
    except Exception:
        derived = {}
    return {k: sorted(set(plan.get(k) or []) | set(derived.get(k) or []))
            for k in _SEED_EXPECTATION_KEYS}


def _execute_sync(rp: RunPaths, job: Job) -> dict:
    from . import browser as B
    from . import crosscheck, flows
    from . import seed as seeder
    from . import snapshot as snap
    from .findings import Ledger
    from .oracles import canvas as ocanvas
    from .oracles import db as odb
    from .oracles import disk as odisk
    from .oracles import log as olog

    restored = snap.restore(job.snapshot, rp.downloads)
    folder = Path(restored["path"])
    if not restored.get("verify", {}).get("ok", True):
        return {"ok": False, "reason": "snapshot restore did not verify",
                "verify": restored.get("verify")}

    add_sync_pair(rp, folder, job.course_id)
    # NOT `job.seed_kinds or None` - that collapses the empty list back into
    # "seed everything", which is the opposite of what an empty list asks for.
    # Named by ROW, not by folder. A lane runs many rows against the same
    # snapshot, so `seed_<folder>.json` was overwritten by each one - the file
    # on disk described only the LAST row that happened to use that folder, and
    # any re-check of an earlier row would have been held to a plan it never
    # ran. The folder-named copy is kept as well, because it is what a person
    # looks for when reading a single scenario by hand.
    plan = seeder.seed(folder, job.seed_kinds, job.seed_counts or None,
                       out_path=Path(rp.evidence) / f"seed_{job.id}.json")
    try:
        (Path(rp.evidence) / f"seed_{folder.name}.json").write_text(
            json.dumps(plan, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
    except OSError:
        pass
    odisk.save(odisk.scan(folder, full_hash=True),
               Path(rp.evidence) / f"disk_{job.id}_before.json")

    with B.session(rp) as s:
        f = flows.SyncFlow(s, rp)
        res = {"name": job.name, "open": f.open()}
        res["analyze"] = f.analyze(job.name, quick=job.quick)
        landed = res["analyze"].get("landed_on")
        # A sync with nothing to do does not stop at Review at all - it runs
        # straight to "Sync done - everything up to date. Checked N files in
        # this course - your folder already matches Canvas." That is the right
        # behaviour and a terminal screen, so there is nothing to confirm.
        # Treating it as a review screen produced "no host for key
        # btn_sync_selected", which reads like the app lost its own button.
        already_done = landed == "complete"
        on_review = landed == "review"
        if on_review:
            # Capture the screen's OWN defaults first, then tick, then capture
            # again - the outcome checks need what was actually selected, and
            # the first capture is the evidence for what the app proposed.
            res["review"] = f.review_snapshot(f"{job.name}_review")
            cats = _categories_to_tick(job.seed_kinds)
            if cats:
                res["select"] = [f.select_category(c) for c in cats]
                res["review"] = f.review_snapshot(f"{job.name}_review")

        if already_done:
            res["confirm"] = {"ok": True, "skipped": "already up to date",
                              "landed_on": landed,
                              "capture": f.capture_screen(
                                  f"{job.name}_up_to_date")}
        elif job.confirm and on_review:
            # Even on the review screen the action can be legitimately
            # unavailable - every row a fixture produced may sit in a category
            # that is unticked by design. Ask the DOM rather than assume.
            if f.has_syncable_selection():
                res["confirm"] = f.confirm(job.name)
            else:
                res["confirm"] = {"ok": True, "skipped": "nothing selected",
                                  "capture": f.capture_screen(
                                      f"{job.name}_nothing_selected")}
        elif landed in ("", "select", "analyze"):
            # The wait returned without the run having got anywhere. Do not go
            # hunting for a button: say so, with the screen as evidence.
            res["confirm"] = {"ok": False, "reason": "analysis never completed",
                              "landed_on": landed,
                              "capture": f.capture_screen(
                                  f"{job.name}_stuck_in_analysis")}
        elif job.quick:
            # Quick Sync has no review screen and no confirmation dialog by
            # design - it is already downloading by the time analyze returns.
            # There is nothing to click; follow it to its terminal screen.
            res["confirm"] = f.wait_terminal(job.name)
        elif job.confirm:
            res["confirm"] = f.confirm(job.name)
        res["trace"] = f.trace
    flows.save_trace(rp, job.name, res)

    after = odisk.scan(folder, full_hash=True)
    odisk.save(after, Path(rp.evidence) / f"disk_{job.id}_after.json")
    ui = _ui_capture(rp, f"{job.name}_review")
    ev = crosscheck.Evidence(
        folder=folder, disk=after, db=odb.read(folder),
        log=olog.parse_and_summarize(str(folder / "debug_log.txt")),
        ui=ui, canvas=ocanvas.snapshot(job.course_id, rp.canvas),
        expect=seed_expectations(plan),
        scenario=job.id)
    found = Ledger(rp.findings).extend(
        crosscheck.invariants(ev) +
        crosscheck.sync_run(ev, plan, ui.get("review"),
                            _sync_outcome_disk(job, after)))
    # The pair goes with the folder. `sync_ui._can_sync` is
    # `bool(sync_pairs) and not _has_missing_folders`, so a pair still pointing
    # at the folder this row just deleted DISABLES the Analyze button for every
    # later row in the lane. The app is right to refuse a broken pair; the
    # audit simply has to clean up after itself.
    unpaired = remove_sync_pair(rp, folder, job.course_id)
    harvest = _harvest_and_prune(rp, job.id, folder)
    return {"ok": bool(res.get("analyze", {}).get("ok")),
            "unpaired": unpaired,
            "kind": "sync", "course_id": job.course_id, "folder": str(folder),
            "landed_on": res["analyze"].get("landed_on"), "harvest": harvest,
            "findings": len(found), "severities": _tally(x.severity for x in found)}


# --------------------------------------------------------------------------
# per-row isolation: disk and the batch log
# --------------------------------------------------------------------------
#
# A lane keeps ONE application alive across all its rows, which is what makes
# the matrix affordable - and it means two things leak from row to row unless
# they are cut explicitly.
#
# **The folder.** The download engine skips a file that already exists at the
# matching size. A second row against the same course would therefore download
# nothing, pass every check, and prove nothing. With 73 rows over 5 courses
# that is not an edge case, it is the common case.
#
# **The batch log.** ``downloads/debug_log.txt`` is cleared once per Streamlit
# SESSION (app.py, "_debug_log_cleared") and appended to for ever after. Oracle
# O2 read whole-file, so row 40 would be judged against the concatenated
# output of rows 1-40 - every earlier row's errors attributed to it.

# ``clear_debug_log`` truncates the file and writes this header. The app calls
# it once per Streamlit SESSION, and every row opens a fresh browser session -
# so between reading the mark and reading the slice, the file is usually a
# different file that merely has the same name.
_LOG_HEADER = b"--- Debug Log Started:"
_MARK_BYTES = 512


def _log_size(p: Path) -> tuple[int, bytes]:
    """A mark to slice from later: the size AND enough of the head to tell
    whether it is still the same file."""
    try:
        with p.open("rb") as fh:
            head = fh.read(_MARK_BYTES)
        return p.stat().st_size, head
    except OSError:
        return 0, b""


def _log_slice(rp: RunPaths, job_id: str, mark) -> str:
    """This row's share of the batch log, as a file the oracle can parse.

    **A byte offset alone is wrong here, and it fabricated a HIGH finding on
    the very first two-course row.** The app clears the batch log at the start
    of every Streamlit session (app.py, ``_debug_log_cleared``), and every row
    opens a new browser session - so the offset taken before the flow indexes
    into a file that no longer exists. Measured on the smoke run: row 2's mark
    was 13,183 bytes from row 1's log; the recreated file grew past that, so
    nothing looked wrong, and slicing from 13,183 silently discarded the ENTIRE
    first course of a two-course row. The check that compares logged writes
    against files on disk then reported "log records 22 writes but 18 content
    files exist" - a defect in the harness, filed against the product.

    Three cases, and only the first is obvious:

    * the file was REPLACED (head no longer matches) -> the mark is meaningless
      and everything present belongs to this row;
    * the file SHRANK below the mark (``log_debug`` rotates at 5 MB) -> same;
    * otherwise slice from the mark, then drop anything before the LAST session
      header inside it, which is where this row's session actually began.
    """
    size, head = mark if isinstance(mark, tuple) else (int(mark or 0), b"")
    src = rp.batch_debug_log()
    dst = Path(rp.logs) / f"{job_id}.txt"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = src.read_bytes()
    except OSError:
        data = b""

    same_file = bool(head) and data[:len(head)] == head
    if same_file and 0 < size <= len(data):
        data = data[size:]

    cut = data.rfind(_LOG_HEADER)
    if cut > 0:
        data = data[cut:]

    dst.write_bytes(data)
    return str(dst)


# ``canvas_logic`` opens each course's download with this banner, and it is the
# only line carrying the course id, which is what makes it usable as a split
# point (a course NAME would have to survive sanitisation and duplicate titles).
_COURSE_BANNER = re.compile(r"^-{3} Download: .* \(ID: (\d+)\) Mode: ", re.M)
# The same banner, read for the NAME instead - which is how the batch-level
# Panopto lines identify the course they are about (they carry no id).
_COURSE_BANNER_NAME = re.compile(r"^-{3} Download: (.*) \(ID: \d+\) Mode: ", re.M)
# Phases that run ONCE for the whole batch, after every course banner, and so
# cannot be attributed by position. Each of these lines names its course.
_BATCH_PHASE_RE = re.compile(r"\[panopto\.[a-z_]+\]")


def _row_log_summary(olog, row_log: str) -> dict:
    """The row's whole log, parsed once - never fatal.

    Only the batch-level phases need it, and a checker must not lose a row's
    other findings because one log could not be read.
    """
    try:
        return olog.parse_and_summarize(str(row_log))
    except Exception:
        return {}


def _log_for_course(slice_path: str, course_id: int, out_path: Path) -> str:
    """One course's share of a row's log.

    A row may select several courses, and the batch log is one file for all of
    them - so comparing it against ONE course's folder counts the others'
    writes. Measured on the first two-course smoke row: 39 logged writes
    (23 files + 16 Canvas Content, across both courses) against 18 files on the
    smaller course's disk, reported as "files the log says were saved are not
    present", severity high. Twice, once per course.

    Everything for a course sits between its banner and the next one -
    including its post-processing block, which the app emits after
    "Course Finished" but before the next course starts. The preamble above the
    first banner is the shared scan phase and carries no delivery events.

    **The Panopto phase is the exception, and it is not a small one.** It runs
    ONCE for the whole batch, after every course's banner, so position puts all
    of it in the LAST course's slice - including the lines about the others.
    Measured on m041 (43660 + 45899): 43660's slice held 0 Panopto lines while
    45899's held 114, among them
    ``Discovered 36 recording(s) in 'Indføring i organisationers ...'`` - a line
    about 43660. The delivery check read 43660's empty slice and reported
    "Panopto was requested but nothing was discovered (36 recordings expected)"
    about the one course that had discovered all 36. The real answer for 45899
    was in that same block: its module items launch-resolve to the library's
    Alma tool, not Panopto, and it legitimately has none.

    Those lines NAME their course, so they are routed by name rather than by
    position. Appended after the positional body so ordering within the course
    is preserved and the phase reads as what it is - something that happened at
    the end of the run.

    Falls back to the whole slice when no banner is found, so a log shape
    change degrades to the old (noisy) behaviour rather than to an empty file
    that would make every log check pass by default.
    """
    text = Path(slice_path).read_text(encoding="utf-8", errors="replace")
    marks = [(m.start(), int(m.group(1))) for m in _COURSE_BANNER.finditer(text)]
    body = text
    course_name = ""
    for i, (pos, cid) in enumerate(marks):
        if cid == course_id:
            end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            body = text[pos:end]
            m = _COURSE_BANNER_NAME.search(text[pos:end])
            course_name = (m.group(1).strip() if m else "")
            break

    if marks:
        # Routing has to work in BOTH directions or it only half-helps: the
        # last course keeps the whole tail positionally, so a line naming
        # another course has to be taken OUT of its body as well as added to
        # the right one. A batch-phase line naming no course at all is left
        # where it fell - unattributable, and guessing would be worse.
        names = {n for n in
                 (m.group(1).strip() for m in _COURSE_BANNER_NAME.finditer(text))
                 if n}

        def _owner(line: str) -> str | None:
            named = [n for n in names if f"'{n}'" in line]
            return named[0] if len(named) == 1 else None

        kept = [ln for ln in body.splitlines()
                if not (_BATCH_PHASE_RE.search(ln)
                        and (_o := _owner(ln)) and _o != course_name)]
        # Rebuild ONLY when something was actually removed. Round-tripping
        # through splitlines/join otherwise drops the trailing newline, and the
        # no-banner fallback is supposed to return the text untouched.
        if len(kept) != len(body.splitlines()):
            body = "\n".join(kept) + "\n"
        if course_name:
            tail = text[marks[-1][0]:]
            claimed = [ln for ln in tail.splitlines()
                       if _BATCH_PHASE_RE.search(ln) and _owner(ln) == course_name]
            missing = [ln for ln in claimed if ln not in body]
            if missing:
                body = body.rstrip("\n") + "\n" + "\n".join(missing) + "\n"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return str(out_path)


# Everything the audit reasons about is EXTRACTED before the payload goes:
# a full-hash disk scan (every path, size and md5), the manifest, the log
# slice, the UI capture and the findings. Keeping the bytes as well would cost
# ~90 GB across the matrix against 64.5 GB free, and buys nothing a re-run of
# the single row cannot reproduce - progress.json makes that one command.
_HARVEST = (".canvas_sync.db", "debug_log.txt", "download_errors.txt")


def _harvest_and_prune(rp: RunPaths, job_id: str, folder: Path) -> dict:
    """Copy the small per-course artefacts out, then delete the folder."""
    from . import snapshot as snap
    out = Path(rp.evidence) / "rows" / job_id
    out.mkdir(parents=True, exist_ok=True)
    kept = []
    for name in _HARVEST:
        src = folder / name
        if src.is_file():
            try:
                shutil.copy2(src, out / name)
                kept.append(name)
            except OSError:
                pass
    try:
        snap._rmtree(folder)
        removed = True
    except Exception as e:                      # noqa: BLE001 - never fatal
        removed = f"{type(e).__name__}: {e}"
    return {"kept": kept, "removed": removed, "evidence": str(out)}


def _prune_course_folder(rp: RunPaths, course_id: int) -> str:
    """Delete a previous row's folder for this course, if one survived."""
    folder = _course_folder(rp, course_id)
    if folder is None:
        return ""
    from . import snapshot as snap
    try:
        snap._rmtree(folder)
        return str(folder)
    except Exception as e:                      # noqa: BLE001
        return f"FAILED {folder}: {type(e).__name__}: {e}"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _course_folder(rp: RunPaths, course_id: int) -> Path | None:
    """The folder the download actually produced, found by its manifest.

    Matched on the manifest's bound course id rather than on a name guessed from
    the Canvas course name: the app sanitises folder names, and a guess that is
    subtly wrong would report "the download produced nothing" for a download
    that worked perfectly.
    """
    import sqlite3
    for d in sorted(p for p in rp.downloads.iterdir() if p.is_dir()):
        db = d / ".canvas_sync.db"
        if not db.is_file():
            continue
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            try:
                row = con.execute(
                    "SELECT value FROM sync_metadata WHERE key='course_id'").fetchone()
            finally:
                con.close()
        except sqlite3.Error:
            continue
        if row and str(row[0]).strip() == str(course_id):
            return d
    return None


def _ui_capture(rp: RunPaths, name: str) -> dict:
    p = Path(rp.ui) / f"{name}.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _tally(items) -> dict:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def _unapplied_note(factors: list[str], label: str, cid: int) -> list:
    """Say out loud that the row did not test what its plan claims.

    Silently narrowing the expectation would turn a fabricated defect into a
    fabricated PASS, which is the worse direction - the row still counts toward
    the coverage the report prints.
    """
    if not factors:
        return []
    # Deferred, like every other crosscheck use in this module - importing it at
    # module scope pulls the oracle stack into the CLI's cold path.
    from . import crosscheck
    return [crosscheck.observation(
        title=f"{len(factors)} factor(s) were never applied to the UI on this row",
        detail="The driver could not reach these controls, so the app was never "
               "asked for them and this row does not exercise them. They are "
               "excluded from its expectations rather than reported as product "
               "defects. The row is marked failed and re-runs on resume: "
               + ", ".join(factors),
        scenario=label, course=str(cid), evidence={"factors": factors})]


def unapplied_factors(rp: RunPaths, name: str) -> list[str]:
    """Factors the UI driver could NOT set on this row, read from its trace.

    `configure` records every toggle it failed to reach (a card that re-rendered
    mid-loop leaves the later controls absent for a beat). Those factors were
    never delivered to the app, so the row did not test them.
    """
    try:
        t = json.loads((Path(rp.ui) / f"{name}_flow.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    return sorted({f.get("factor") for f in (t.get("configure") or {}).get("failed", [])
                   if f.get("factor")})


def expect_for(rp: RunPaths, job: Job) -> tuple[dict, list[str]]:
    """The row's config, minus anything the UI never actually applied.

    **A factor the driver failed to set must not be held against the product.**
    Measured 2026-08-08 on m014: `configure` reported `convert_excel` and four
    siblings as "control not present (card collapsed?)", so the app was never
    told to convert; its contract correctly recorded convert_excel=False and it
    correctly left the 50 .xlsx alone. Checked against the REQUESTED config that
    produced three findings - a HIGH ("set to True but the folder contract says
    False") plus two mediums - all three describing the audit's own failure to
    click a button. Same class as RUNBOOK checker-defect 9, where the size cap
    was accepted into every row and applied to none.

    Dropping the key is deliberately different from setting it False: `_conversions`
    and the OFF-must-not-consume mirror check both skip a factor that is ABSENT,
    so the row is judged on what it really ran, while a False would assert the
    opposite expectation just as wrongly.

    Shared by the live pass and `recheck` so the two cannot drift - the same
    reason `seed_expectations` exists on the sync side.
    """
    bad = unapplied_factors(rp, job.name)
    if not bad:
        return job.config, []
    return {k: v for k, v in job.config.items() if k not in bad}, bad


def _recheck_sync(lrp: RunPaths, job: Job, ui: dict, ledger, skipped: list,
                  lane: str) -> int:
    """Re-derive one sync row's findings from its saved evidence."""
    from . import crosscheck
    from .oracles import canvas as ocanvas
    from .oracles import db as odb
    from .oracles import log as olog

    ev_dir = Path(lrp.evidence)
    after_p = ev_dir / f"disk_{job.id}_after.json"
    rows_p = ev_dir / "rows" / job.id
    if not after_p.is_file() or not rows_p.is_dir():
        skipped.append({"lane": lane, "row": job.id,
                        "reason": "evidence incomplete (row may not have run)"})
        return 0

    # Row-unique first. The folder-named copy is the older layout and describes
    # only the LAST row that used that folder, so it is a fallback that has to
    # be REPORTED rather than trusted: holding a row to another row's plan
    # invents fixture failures out of nothing.
    plan_p = ev_dir / f"seed_{job.id}.json"
    approximate = not plan_p.is_file()
    plan = {}
    if not approximate:
        try:
            plan = json.loads(plan_p.read_text(encoding="utf-8"))
        except Exception:
            plan = {}
    else:
        skipped.append({"lane": lane, "row": job.id,
                        "reason": "seed plan is not row-unique (older layout); "
                                  "fixture outcomes not re-checked"})

    after = json.loads(after_p.read_text(encoding="utf-8"))
    log_p = rows_p / "debug_log.txt"
    ev = crosscheck.Evidence(
        folder=Path(rows_p), scenario=job.id, disk=after, db=odb.read(rows_p),
        log=olog.parse_and_summarize(str(log_p)) if log_p.is_file() else {},
        ui=ui, canvas=ocanvas.snapshot(job.course_id, lrp.canvas),
        expect=seed_expectations(plan))
    checks = crosscheck.invariants(ev)
    if plan:
        # `after` ONLY when a sync actually ran - the same gate the live row
        # applies, and for the same reason (see _execute_sync). A re-check that
        # forgets it holds a folder which stopped at the REVIEW screen to the
        # outcomes of a sync that never happened, and every outcome check then
        # fabricates a failure: measured here, 26 criticals out of thin air on
        # a run whose live pass reported none, 21 of them the very
        # "locally edited but no _NewVersion sibling" class already recorded as
        # invalid in the register. The rule lived in one place and this is the
        # second - `_sync_outcome_disk` now holds it so there is no third.
        checks += crosscheck.sync_run(ev, plan, ui.get("review"),
                                      _sync_outcome_disk(job, after))
    ledger.extend(checks)
    return len(checks)


def recheck(parent: RunPaths) -> dict:
    """Re-derive every lane's findings from its saved evidence, with the
    CURRENT checker.

    A finding is not a historical record - it is a function of (evidence,
    checker), and only the evidence is expensive. A worker imports
    ``crosscheck`` when it starts, so a checker defect fixed during a six-hour
    run keeps producing the old verdict for every row after it: the Excel
    sidecar false HIGH was fixed forty minutes in, and every later Excel row
    would still have carried it.

    This is why a row harvests its manifest, its disk scan (full hashes), its
    log slice and its UI capture before deleting the payload - between them
    they are everything the checks read, so a re-check is seconds and needs no
    network, no browser and no re-download.

    Rows whose evidence is incomplete are REPORTED, never silently skipped: a
    row missing from a re-check is a row nobody is checking.
    """
    from . import crosscheck
    from .findings import Ledger
    from .oracles import canvas as ocanvas
    from .oracles import db as odb
    from .oracles import log as olog

    plan_path = parent.root / "lanes.json"
    if not plan_path.is_file():
        return {"status": "no-plan"}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    lanes, skipped = [], []
    for lane in plan["lanes"]:
        lrp = RunPaths(lane["run_id"])
        spec_path = lrp.root / "lane_spec.json"
        if not spec_path.is_file():
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        # Written fresh: the whole point is to replace the old verdicts. Always
        # CREATED, even when nothing is found - "no findings" and "never
        # re-checked" are different states, and `collect --rechecked` reports
        # the second as a missing lane. A clean lane must not look like a
        # broken one.
        fresh = lrp.root / "findings.rechecked.jsonl"
        fresh.write_text("", encoding="utf-8")
        ledger, n = Ledger(fresh), 0

        for j in spec["jobs"]:
            job = Job(**j)
            # WHICH capture, by kind - not "whichever exists". A download row is
            # judged on its completion screen; a SYNC row is judged on its
            # REVIEW screen, because that capture is the only record of what the
            # user ticked, and half the outcome checks are read against the
            # selection (`_sync_outcome`: a ticked "deleted locally" row flips
            # the fixture's expectation from 'absent' to 'restored'). Both files
            # exist for a synced row, so a `_complete or _review` fallback
            # silently took the one WITHOUT a `review` key - selection unknown,
            # no flip, and the app was reported for restoring the very files the
            # harness had just asked it to restore. Measured: 4 fabricated HIGHs
            # on rows s001 and s006, against a live pass that reported none.
            if job.kind == "sync":
                ui = _ui_capture(lrp, f"{job.name}_review") or \
                    _ui_capture(lrp, f"{job.name}_complete")
            else:
                ui = _ui_capture(lrp, f"{job.name}_complete") or \
                    _ui_capture(lrp, f"{job.name}_review")

            if job.kind == "sync":
                # A sync row's evidence has a different shape - a before/after
                # PAIR rather than one scan, the seed plan that says what was
                # promised, and the log inside the harvested folder. Re-checking
                # it against the download layout reported all 43 rows as
                # "evidence incomplete", which the skip list at least made
                # visible instead of passing them silently.
                n += _recheck_sync(lrp, job, ui, ledger, skipped, lane["lane"])
                continue

            _rc_expect, _rc_unapplied = expect_for(lrp, job)
            for cid in job.course_ids:
                label = job.id if len(job.course_ids) == 1 else f"{job.id}_c{cid}"
                disk_p = Path(lrp.evidence) / f"disk_{label}.json"
                rows_p = Path(lrp.evidence) / "rows" / label
                if not disk_p.is_file() or not rows_p.is_dir():
                    skipped.append({"lane": lane["lane"], "row": label,
                                    "reason": "evidence incomplete (row may "
                                              "not have run)"})
                    continue
                # RE-SLICE from the row log rather than reading the slice the
                # live pass wrote. The slice is a DERIVED artefact, so it is
                # part of the checker, not part of the evidence - and reading
                # the stored one made every slicer fix un-retroactive. That is
                # not hypothetical: the Panopto phase runs once for the whole
                # batch, so its lines were attributed to the wrong course, and
                # no amount of re-checking could have corrected it while the
                # stale slice was the input. Falls back to the stored slice,
                # then to the whole row log, so an older run still re-checks.
                row_log_p = Path(lrp.logs) / f"{job.id}.txt"
                log_p = Path(lrp.logs) / f"{label}_course.txt"
                if row_log_p.is_file():
                    try:
                        log_p = Path(_log_for_course(
                            str(row_log_p), cid,
                            Path(lrp.logs) / f"{label}_course.txt"))
                    except Exception:
                        pass
                ev = crosscheck.Evidence(
                    folder=Path(rows_p), scenario=label,
                    disk=json.loads(disk_p.read_text(encoding="utf-8")),
                    db=odb.read(rows_p),
                    log=olog.parse_and_summarize(str(log_p)) if log_p.is_file() else {},
                    batch_log=_row_log_summary(olog, str(row_log_p))
                    if row_log_p.is_file() else {},
                    ui=ui, canvas=ocanvas.snapshot(cid, lrp.canvas),
                    expect=_rc_expect)
                checks = (crosscheck.invariants(ev) +
                          (crosscheck.download_run(ev) if job.kind == "download"
                           else []) +
                          _unapplied_note(_rc_unapplied, label, cid))
                ledger.extend(checks)
                n += len(checks)
        lanes.append({"lane": lane["lane"], "findings": n, "path": str(fresh)})

    return {"parent": parent.run_id, "lanes": lanes, "skipped": skipped,
            "note": "re-derived from saved evidence with the current checker; "
                    "collect --rechecked merges these instead of the originals"}


def collect(parent: RunPaths, *, rechecked: bool = False) -> dict:
    """Fold every lane's findings into the parent run.

    Each finding keeps the lane it came from, so a defect that appears in one
    lane and not another - the signature of a resource clash rather than a
    product bug - is visible instead of being averaged away.

    ``rechecked=True`` merges what ``recheck()`` re-derived from the saved
    evidence instead of what the workers wrote as they went. Prefer it whenever
    the checker changed mid-run: a worker imports ``crosscheck`` once, at
    startup, so every row after a fix still carries the old verdict.
    """
    plan_path = parent.root / "lanes.json"
    if not plan_path.is_file():
        return {"status": "no-plan"}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    merged, seen, missing = [], set(), []
    for lane in plan["lanes"]:
        lrp = RunPaths(lane["run_id"])
        src = (lrp.root / "findings.rechecked.jsonl") if rechecked else lrp.findings
        if not src.is_file():
            missing.append({"lane": lane["lane"], "expected": str(src)})
            continue
        for line in src.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                f = json.loads(line)
            except Exception:
                continue
            f["lane"] = lane["lane"]
            k = (f.get("category"), f.get("title"), f.get("scenario"))
            if k in seen:
                continue
            seen.add(k)
            merged.append(f)

    # REPLACE the previous merge rather than appending to it. `collect` dedupes
    # only WITHIN one invocation, so running it twice - which the documented
    # workflow invites: `matrix collect` in the setup section, then `matrix
    # recheck` + `matrix collect --rechecked` in the re-check section - appended
    # both sets and inflated every count. Measured 2026-08-08 on the sync run:
    # 92 findings became 186, all 92 keys duplicated exactly twice, so "0
    # defects" stayed right while every total doubled.
    #
    # A finding that came from a lane carries `lane`; one the agent recorded by
    # hand does not. Only the lane half is rebuilt, so `finding add` survives a
    # re-collect - otherwise a routine command would destroy the agent's own
    # judgment findings, which are exactly the ones no check can produce.
    kept = []
    if parent.findings.is_file():
        for line in parent.findings.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                prev = json.loads(line)
            except Exception:
                continue
            if not prev.get("lane"):
                kept.append(prev)
    with parent.findings.open("w", encoding="utf-8") as fh:
        for f in kept + merged:
            fh.write(json.dumps(f, ensure_ascii=False, default=str) + chr(10))
    out = {"parent": parent.run_id, "merged": len(merged),
           "source": "rechecked" if rechecked else "as-run",
           "lanes": [l["lane"] for l in plan["lanes"]],
           "findings": str(parent.findings)}
    # A lane with no findings file is a lane nobody is reading. Reported rather
    # than skipped, because the merge otherwise succeeds and reports a total
    # that is quietly short by a whole lane.
    if missing:
        out["missing_lanes"] = missing
    return out
