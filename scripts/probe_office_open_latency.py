"""How long after ``open`` does OUR document actually become frontmost?

The D1 guard binds the document to export by comparing
``name of active <klass>`` with the basename we staged. That is only correct if
``active`` has ALREADY become ours by the time we look - and ``open`` is an
Apple event that returns when the app has accepted it, not when the document is
frontmost.

On an idle machine the gap is invisible, which is precisely why every
measurement taken while building the guard passed. The 2026-08-11 crash
happened with TWO audit lanes running - one transcribing Panopto recordings on
CPU (65 s/recording on this box, all cores busy) while the other drove
PowerPoint. If the gap widens under that load, the guard rejects legitimate
conversions with -30001, trips SYSTEMIC_REPEAT_THRESHOLD, and aborts the phase:
a data-loss bug traded for a load-dependent failure.

So measure it, idle and loaded, rather than assume either way:

    python scripts/probe_office_open_latency.py --app PowerPoint
    python scripts/probe_office_open_latency.py --app PowerPoint --load 10

``--load N`` spins N CPU-burning subprocesses for the duration (this box has 10
cores). Reports the distribution of "iterations until ours is frontmost", which
is exactly the quantity a polling guard has to be sized against.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

APPS = {
    "Word": ("Microsoft Word", "document", ".docx"),
    "Excel": ("Microsoft Excel", "workbook", ".xlsx"),
    "PowerPoint": ("Microsoft PowerPoint", "presentation", ".pptx"),
}


def _burn(stop):
    x = 0
    while not stop.is_set():
        x = (x * x + 1) % 2147483647


def _osa(script: str, timeout: float = 120):
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -9, "", "TIMEOUT"


def _sample(ext: str) -> Path | None:
    for p in (REPO / "_audit_runs").rglob(f"*{ext}"):
        if p.is_file() and 200_000 < p.stat().st_size < 6_000_000:
            return p
    return None


def main() -> int:
    if sys.platform != "darwin":
        print("macOS only", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", choices=sorted(APPS), default="PowerPoint")
    ap.add_argument("--load", type=int, default=0, help="CPU burners to spin")
    ap.add_argument("--n", type=int, default=6, help="documents to open")
    a = ap.parse_args()

    bundle, klass, ext = APPS[a.app]
    src = _sample(ext)
    if src is None:
        print(f"no sample {ext} under _audit_runs", file=sys.stderr)
        return 2

    stop = mp.Event()
    burners = [mp.Process(target=_burn, args=(stop,)) for _ in range(a.load)]
    for b in burners:
        b.start()
    if a.load:
        time.sleep(2)

    # A cold app first, then warm - the first open of a session is the slow one
    # and is exactly when a conversion phase starts.
    _osa(f'tell application "{bundle}" to quit saving no', timeout=60)
    subprocess.run(["pkill", "-x", bundle], capture_output=True)
    time.sleep(2)

    rows = []
    try:
        for i in range(a.n):
            work = Path(tempfile.mkdtemp(prefix="cd_lat_"))
            staged = work / ("src" + ext)
            shutil.copy2(src, staged)
            # POLL inside one osascript: crossing the process boundary per
            # sample would measure osascript startup (~40-80 ms), not the app.
            rc, out, err = _osa(f'''
                tell application "{bundle}"
                    set t0 to (current date)
                    open POSIX file "{staged}"
                    set n to 0
                    set ours to false
                    repeat 400 times
                        try
                            if ((name of active {klass}) is "{staged.name}") then
                                set ours to true
                                exit repeat
                            end if
                        end try
                        set n to n + 1
                        delay 0.05
                    end repeat
                    set el to ((current date) - t0)
                    try
                        if ours then close active {klass} saving no
                    end try
                    return (n as text) & "|" & (ours as text) & "|" & (el as text)
                end tell''')
            if rc == 0 and "|" in out:
                n, ours, el = out.split("|")
                rows.append({"i": i, "polls_before_ours": int(n),
                             "ms_before_ours": int(n) * 50,
                             "found": ours.lower() == "true",
                             "cold": i == 0})
            else:
                rows.append({"i": i, "error": err[:120]})
            shutil.rmtree(work, ignore_errors=True)
    finally:
        stop.set()
        for b in burners:
            b.join(timeout=5)
        _osa(f'tell application "{bundle}" to quit saving no', timeout=60)
        subprocess.run(["pkill", "-x", bundle], capture_output=True)

    got = [r for r in rows if r.get("found")]
    print(json.dumps({
        "app": a.app, "load_procs": a.load, "opens": len(rows),
        "resolved": len(got),
        "polls_before_ours": [r["polls_before_ours"] for r in got],
        "worst_ms": max((r["ms_before_ours"] for r in got), default=None),
        "cold_ms": next((r["ms_before_ours"] for r in got if r["cold"]), None),
        "rows": rows,
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
