"""Run directories and the isolation boundary.

Every audit invocation gets its own run directory under ``_audit_runs/``. The
important part is not the tidiness - it is that the app's ENTIRE persistent
state is redirected into that directory via ``CANVAS_DL_CONFIG_DIR``, so an
audit can never read or write the developer's real settings, sync pairs, sync
history, saved groups, presets or Today list. In dev mode all of those live in
the repo root (``shared.helpers.get_config_dir`` returns ``_REPO_ROOT``), which
is exactly where an un-isolated audit would trample them.

Isolation has to be TOTAL or it is worse than nothing: an audit that isolates
settings but shares sync history would draw conclusions from state it had
polluted itself. ``get_config_dir()`` is the single chokepoint every state
manager already routes through (verified across auth, sync_ui, hub_dialog,
presets, today_dashboard, update_banner, auto_sync, execution), so redirecting
it redirects all of them at once.

Layout of a run directory::

    _audit_runs/<run_id>/
        config/         CANVAS_DL_CONFIG_DIR - all app state lands here
            panopto_models/   junction -> repo copy (models are big; never copied)
            cuda_libs/        junction -> repo copy
        downloads/      the download root the app is pointed at
            <Course Folder>/      per-course output, each with its own debug_log.txt
            debug_log.txt         the batch-level download log
        evidence/
            screenshots/    PNGs the agent reads to judge screens visually
            ui/             per-step UI extractions (JSON)
            canvas/         cached independent Canvas enumerations (oracle O5)
            logs/           copies of debug logs taken at known points in time
        findings.jsonl  append-only findings, one JSON object per line
        report.html     rendered report
        run.json        run metadata + step ledger
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNS_ROOT = REPO_ROOT / "_audit_runs"

# State files the app persists into its config dir. Seeded from the developer's
# real ones where that is useful (settings carries api_url so the keyring lookup
# succeeds and the audit starts signed in), and deliberately NOT seeded where a
# clean slate is the point (pairs/history/groups/presets/today).
SEEDED_FROM_REAL = ("canvas_downloader_settings.json",)
CLEAN_SLATE = {
    "canvas_sync_pairs.json": [],
    "canvas_sync_history.json": [],
    "saved_sync_groups.json": [],
    "saved_download_presets.json": [],
}
# Heavy directories shared with the repo rather than copied. A junction (not a
# symlink) because junctions need no admin rights on Windows.
LINKED_DIRS = ("panopto_models", "cuda_libs")


class RunPaths:
    """Resolved paths for one audit run. Cheap to construct; creates nothing."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.root = RUNS_ROOT / run_id
        self.config = self.root / "config"
        self.downloads = self.root / "downloads"
        self.evidence = self.root / "evidence"
        self.screenshots = self.evidence / "screenshots"
        self.ui = self.evidence / "ui"
        self.canvas = self.evidence / "canvas"
        self.logs = self.evidence / "logs"
        self.findings = self.root / "findings.jsonl"
        self.report = self.root / "report.html"
        self.meta = self.root / "run.json"
        self.browser_profile = self.root / "browser-profile"

    # -- construction ------------------------------------------------------

    def create(self) -> "RunPaths":
        for d in (self.root, self.config, self.downloads, self.evidence,
                  self.screenshots, self.ui, self.canvas, self.logs,
                  self.browser_profile):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def batch_debug_log(self) -> Path:
        """The download-mode debug log, written at the root of the download dir."""
        return self.downloads / "debug_log.txt"

    def course_dir(self, folder_name: str) -> Path:
        return self.downloads / folder_name

    # -- metadata ledger ---------------------------------------------------

    def load_meta(self) -> dict:
        if self.meta.is_file():
            try:
                return json.loads(self.meta.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def save_meta(self, data: dict) -> None:
        self.meta.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                             encoding="utf-8")

    def update_meta(self, **kv) -> dict:
        meta = self.load_meta()
        meta.update(kv)
        self.save_meta(meta)
        return meta

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "root": str(self.root),
            "config": str(self.config),
            "downloads": str(self.downloads),
            "evidence": str(self.evidence),
            "screenshots": str(self.screenshots),
            "findings": str(self.findings),
            "report": str(self.report),
        }


# --------------------------------------------------------------------------
# run lifecycle
# --------------------------------------------------------------------------

def new_run(label: str = "") -> RunPaths:
    """Create a fresh run directory and provision its isolated config dir."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{stamp}_{label}" if label else stamp
    rp = RunPaths(run_id).create()
    provision_config_dir(rp)
    rp.save_meta({
        "run_id": run_id,
        "label": label,
        "created": datetime.now().isoformat(timespec="seconds"),
        "repo_root": str(REPO_ROOT),
        "steps": [],
    })
    _write_pointer(run_id)
    return rp


def latest_run() -> RunPaths | None:
    """The run the CLI acts on when none is named - see ``_write_pointer``."""
    ptr = RUNS_ROOT / "CURRENT"
    if ptr.is_file():
        rid = ptr.read_text(encoding="utf-8").strip()
        if rid and (RUNS_ROOT / rid).is_dir():
            return RunPaths(rid)
    if not RUNS_ROOT.is_dir():
        return None
    dirs = sorted((d for d in RUNS_ROOT.iterdir() if d.is_dir() and d.name != "CURRENT"),
                  key=lambda d: d.name)
    return RunPaths(dirs[-1].name) if dirs else None


def use_run(run_id: str, make_current: bool = True) -> RunPaths:
    rp = RunPaths(run_id)
    if not rp.root.is_dir():
        raise SystemExit(f"No such run: {run_id} (looked in {RUNS_ROOT})")
    if make_current:
        _write_pointer(run_id)
    return rp


def _write_pointer(run_id: str) -> None:
    """Record the active run so successive CLI calls agree without the agent
    having to thread a run id through every command - which is exactly the kind
    of bookkeeping that goes wrong silently halfway through a long audit."""
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    (RUNS_ROOT / "CURRENT").write_text(run_id, encoding="utf-8")


def list_runs() -> list[dict]:
    if not RUNS_ROOT.is_dir():
        return []
    out = []
    for d in sorted(RUNS_ROOT.iterdir()):
        if not d.is_dir() or d.name == "CURRENT":
            continue
        rp = RunPaths(d.name)
        meta = rp.load_meta()
        out.append({"run_id": d.name, "created": meta.get("created", ""),
                    "label": meta.get("label", ""),
                    "findings": _count_lines(rp.findings)})
    return out


def _count_lines(p: Path) -> int:
    try:
        return sum(1 for _ in p.open(encoding="utf-8"))
    except Exception:
        return 0


# --------------------------------------------------------------------------
# config dir provisioning
# --------------------------------------------------------------------------

def provision_config_dir(rp: RunPaths) -> None:
    """Fill the isolated config dir so the app starts signed in but stateless.

    Signed in, because a login wall would make every run start with manual
    token entry and the audit is meant to be unattended. Stateless, because
    every sync pair, history entry and saved group the audit reasons about must
    be one it created itself - otherwise a finding like "the Today page lists a
    course that isn't in the daily set" could just be the developer's own
    leftover state showing through.
    """
    rp.config.mkdir(parents=True, exist_ok=True)

    for name in SEEDED_FROM_REAL:
        src = REPO_ROOT / name
        dst = rp.config / name
        if src.is_file() and not dst.is_file():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    # Force the settings the audit depends on. debug_mode is non-negotiable:
    # the debug log is oracle O2 and without it the audit is blind.
    settings_path = rp.config / "canvas_downloader_settings.json"
    settings = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            settings = {}
    settings["debug_mode"] = True
    settings["error_log_enabled"] = True
    # A default download path pointing into the run dir means the very first
    # screen is already aimed at the right place, so a mistyped path can never
    # scatter a 900 MB course across the developer's Downloads folder.
    settings["default_download_path"] = str(rp.downloads)
    # Notifications fire OS toasts and play sounds; unattended runs must be quiet.
    settings["notifications_enabled"] = False
    settings.setdefault("show_help_text", True)

    # The size cap is INHERITED from the developer's real settings, and it is a
    # matrix factor - so a run would start from whatever the developer happened
    # to leave switched on, and rows that never touch the factor would test a
    # configuration nobody chose. Every row sets it explicitly; the baseline is
    # off.
    settings["max_file_size_enabled"] = False
    settings["max_file_size_mb"] = 500

    # Transcription needs a model ON DISK. `runner.py` reads
    # settings["panopto"]["model"] and, when it is not installed, emits a
    # warning and SKIPS the transcript outputs - so a row asking for txt/srt
    # would quietly produce none and the delivery check would file it against
    # the product. Pin to an installed model, preferring the smallest: the
    # model decides transcript QUALITY, which is not what a configuration
    # matrix is testing, and it is 3.4x faster (measured: 19.1 s vs 65.0 s per
    # recording, tiny on CUDA vs CPU) across fifteen transcription rows.
    try:
        from panopto import models as _pmodels
        installed = [m for m in ("tiny", "base", "small", "medium", "turbo",
                                 "large-v3")
                     if _pmodels.is_installed(m)]
    except Exception:
        installed = []
    pan = dict(settings.get("panopto") or {})
    if installed and pan.get("model") not in installed:
        pan["model"] = installed[0]
    settings["panopto"] = pan

    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False),
                             encoding="utf-8")

    for name, empty in CLEAN_SLATE.items():
        p = rp.config / name
        if not p.is_file():
            p.write_text(json.dumps(empty, indent=2), encoding="utf-8")

    # today_dashboard.json is written by core.today_store with its own shape;
    # start from "no daily courses, auto-sync off" so a run only ever syncs what
    # the audit explicitly asked for.
    today = rp.config / "today_dashboard.json"
    if not today.is_file():
        today.write_text(json.dumps({"auto_sync_enabled": False, "pairs": [],
                                     "last_auto_sync_date": "",
                                     "fda_nudge_dismissed": True}, indent=2),
                         encoding="utf-8")

    for name in LINKED_DIRS:
        _link_dir(REPO_ROOT / name, rp.config / name)


def _link_dir(src: Path, dst: Path) -> None:
    """Junction *dst* -> *src*, falling back to a plain copy-free skip.

    Whisper models are hundreds of MB and the CUDA runtime is over a gigabyte;
    copying either per run would make the audit unusable. A junction needs no
    admin rights on Windows (unlike a symlink), and on POSIX a symlink does.
    """
    if dst.exists() or not src.is_dir():
        return
    try:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)],
                           check=True, capture_output=True)
        else:
            dst.symlink_to(src, target_is_directory=True)
    except Exception:
        # Not fatal: the app will simply report no model installed, which the
        # Panopto phase reports as a finding rather than crashing on.
        pass


# --------------------------------------------------------------------------
# writing the app's own state files
# --------------------------------------------------------------------------
#
# The app's "Add Course" button opens a NATIVE folder picker
# (``shared.helpers.pick_folder`` -> tkinter on Windows, osascript on macOS),
# which is an OS dialog with no DOM - Playwright cannot drive it at all. So a
# pair has to be written straight into the run's isolated state for the sync
# flow to be reachable unattended. That is an acknowledged coverage gap, not a
# hidden one: the picker itself is on the manual-verification list.
#
# These live here rather than in the CLI because the parallel workers need them
# too, and a second writer of the same on-disk format is precisely how two
# callers drift into producing subtly different pair records.

def add_sync_pair(rp: RunPaths, folder, course_id: int,
                  course_name: str = "") -> dict:
    """Register (or re-register) one folder <-> course pair."""
    entry = _pair_entry(folder, course_id, course_name)
    pairs = _read_json(rp.config / "canvas_sync_pairs.json", [])
    pairs = [p for p in pairs if not _same_pair(p, entry)]
    pairs.append({**entry, "last_synced": ""})
    _write_json(rp.config / "canvas_sync_pairs.json", pairs)
    return {"pairs": len(pairs), "added": entry}


def remove_sync_pair(rp: RunPaths, folder, course_id: int) -> dict:
    """Unregister one pair. The inverse of ``add_sync_pair``.

    A sync row deletes its folder once the evidence is out, and a pair left
    pointing at a folder that no longer exists BLOCKS THE WHOLE SYNC PAGE:
    ``sync_ui._can_sync`` is ``bool(sync_pairs) and not _has_missing_folders``,
    which is correct - the app should not sync a broken pair - but it means the
    audit's own cleanup disables the Analyze button for every row after the
    first. Measured on a two-row lane: row 2 timed out clicking a button that
    was ``<button disabled>`` because row 1's folder had been pruned.
    """
    entry = _pair_entry(folder, course_id, "")
    path = rp.config / "canvas_sync_pairs.json"
    pairs = _read_json(path, [])
    kept = [p for p in pairs if not _same_pair(p, entry)]
    _write_json(path, kept)
    return {"pairs": len(kept), "removed": len(pairs) - len(kept)}


def save_hub_pair(rp: RunPaths, folder, course_id: int,
                  course_name: str = "") -> dict:
    """Save a pair into the HUB (``saved_sync_groups.json``), as the app does.

    ``canvas_sync_pairs.json`` is the ACTIVE pair list on the Sync page; the hub
    is a separate, deliberate "save this for later" store. A standalone saved
    pair lives in the hub as a group carrying ``is_single_pair: True`` - that is
    what ``ui/hub_dialog.py`` writes.

    This matters because the Today page imports ONLY from the hub, and
    ``core.auto_sync.reconcile_daily_list_with_hub()`` drops any daily entry the
    hub does not have. Writing an active pair alone and then adding it to the
    daily list produces an orphan that the app correctly deletes on the next
    render - which looks exactly like "the Today page loses my courses" and is
    really the harness having skipped a step the user cannot skip.
    """
    import uuid
    entry = _pair_entry(folder, course_id, course_name)
    p = rp.config / "saved_sync_groups.json"
    data = _read_json(p, {})
    if not isinstance(data, dict):
        data = {}
    groups = data.get("groups")
    if not isinstance(groups, list):
        groups = []
    groups = [g for g in groups
              if not any(_same_pair(x, entry) for x in (g.get("pairs") or []))]
    groups.append({"group_id": f"grp_{uuid.uuid4().hex}",
                   "group_name": entry["course_name"],
                   "pairs": [entry], "is_single_pair": True})
    data["groups"] = groups
    _write_json(p, data)
    return {"hub_entries": len(groups), "saved": entry}


def set_today_pair(rp: RunPaths, folder, course_id: int, course_name: str = "",
                   remove: bool = False, auto_sync: bool | None = None) -> dict:
    """Put a pair in (or take it out of) the daily-sync set.

    Adding also saves the pair to the hub when it is not there already: the
    daily list holds COPIES that are reconciled against the hub on every Today
    render, so a daily entry with no hub counterpart is an orphan and is
    correctly dropped.
    """
    entry = _pair_entry(folder, course_id, course_name)
    if not remove and not _in_hub(rp, entry):
        save_hub_pair(rp, folder, course_id, course_name)
    today = _read_json(rp.config / "today_dashboard.json",
                       {"auto_sync_enabled": False, "pairs": []})
    tp = [p for p in today.get("pairs", []) if not _same_pair(p, entry)]
    if not remove:
        tp.append(entry)
    today["pairs"] = tp
    if auto_sync is not None:
        today["auto_sync_enabled"] = bool(auto_sync)
    _write_json(rp.config / "today_dashboard.json", today)
    return {"today_pairs": len(tp),
            "auto_sync_enabled": today.get("auto_sync_enabled")}


def _pair_entry(folder, course_id: int, course_name: str = "") -> dict:
    p = Path(folder).resolve()
    return {"local_folder": str(p).replace("\\", "/"), "course_id": int(course_id),
            "course_name": course_name or p.name}


def _in_hub(rp: RunPaths, entry: dict) -> bool:
    data = _read_json(rp.config / "saved_sync_groups.json", {})
    groups = (data or {}).get("groups") if isinstance(data, dict) else None
    for g in groups or []:
        if any(_same_pair(x, entry) for x in (g.get("pairs") or [])):
            return True
    return False


def _same_pair(a: dict, b: dict) -> bool:
    return (a.get("course_id") == b.get("course_id")
            and str(a.get("local_folder", "")).replace("\\", "/")
            == b.get("local_folder"))


def _read_json(p: Path, default):
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _write_json(p: Path, data) -> None:
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def app_env(rp: RunPaths, extra: dict | None = None) -> dict:
    """Environment for a child process that must see the isolated state."""
    env = dict(os.environ)
    env["CANVAS_DL_CONFIG_DIR"] = str(rp.config)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


def resolve(run_id: str | None) -> RunPaths:
    """The CLI's single entry point for "which run am I acting on".

    ``--run X`` scopes ONE invocation and deliberately does NOT move the CURRENT
    pointer; only ``run use`` does that. It used to, which made a read-only
    query re-point every later command in the session: ``register show --run
    <old>`` silently switched the working run back, and the commands after it
    started a second app, attached a stale browser and were minutes from
    recording an entire phase's findings against the wrong run.
    """
    if run_id:
        return use_run(run_id, make_current=False)
    rp = latest_run()
    if rp is None:
        raise SystemExit("No audit runs exist yet. Start one with: "
                         "python -m tests.audit run new")
    return rp


if __name__ == "__main__":  # tiny self-check
    print(json.dumps({"repo_root": str(REPO_ROOT), "runs_root": str(RUNS_ROOT),
                      "python": sys.version.split()[0]}, indent=2))
