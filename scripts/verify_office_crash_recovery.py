"""Kill PowerPoint mid-batch. Does the run recover, or abandon the rest?

THE DEFECT THIS PROVES (D6, shipped 2026-08-11): the 2026-08-11 download matrix
crashed PowerPoint mid-phase; the next Apple event returned -600 "Application
isn't running"; that was classified `app_missing`, which is FATAL; and **57
files were abandoned for the rest of the run** while the user was told an app
they had just watched convert forty files "is not installed".

The operator's hypothesis for WHY it crashed is memory/CPU pressure: the matrix
ran two lanes, one transcribing Panopto recordings on CPU (65 s/recording on
this box, all cores busy) while the other drove PowerPoint. That is plausible
and is tested separately by `--load`; but a crash reproduction is a race, and a
race is poor evidence. So this script INJECTS the crash instead - it kills
PowerPoint at a chosen point in a real conversion batch and measures what the
real post-processing phase does next. Forcing the exact condition beats hoping
to win a race.

    python scripts/verify_office_crash_recovery.py                # inject at file 2
    python scripts/verify_office_crash_recovery.py --kill-at 3 --files 8
    python scripts/verify_office_crash_recovery.py --no-kill      # control

What must hold after the kill:

  * every remaining file still converts (the phase is NOT abandoned)
  * the user's own open document is untouched
  * no orphaned/stub PDFs are left in the folder
  * the sources of successful conversions are consumed, and only those
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

BUNDLE = "Microsoft PowerPoint"


def _osa(script: str, timeout: float = 60) -> str:
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return f"ERR {e}"


def _running() -> bool:
    return subprocess.run(["pgrep", "-x", BUNDLE], capture_output=True).returncode == 0


def _quit() -> None:
    _osa(f'tell application "{BUNDLE}" to quit saving no')
    time.sleep(1.5)
    subprocess.run(["pkill", "-x", BUNDLE], capture_output=True)
    time.sleep(1.0)


def _samples(n: int) -> list[Path]:
    out, seen = [], set()
    for p in (REPO / "_audit_runs").rglob("*.pptx"):
        if p.is_file() and 50_000 < p.stat().st_size < 12_000_000 and p.name not in seen:
            seen.add(p.name)
            out.append(p)
            if len(out) >= n:
                break
    return out


def _burn(ev):
    """CPU burner. MODULE level, because macOS spawns rather than forks and a
    local closure cannot be pickled."""
    x = 0
    while not ev.is_set():
        x = (x * x + 1) % 2147483647


def _hog(ev, gb: int):
    """Hold *gb* GiB resident.

    The operator's hypothesis for the 2026-08-11 crash is the OTHER audit lane
    transcribing on CPU - and faster-whisper is as much a MEMORY event as a CPU
    one (model weights + audio buffers). CPU burners alone reproduce half the
    condition; a heavy app like PowerPoint is far likelier to die on memory.
    Touched once per page so the pages are really resident, not just reserved.
    """
    try:
        buf = bytearray(gb * 1024 * 1024 * 1024)
        for i in range(0, len(buf), 4096):
            buf[i] = 1
        while not ev.is_set():
            time.sleep(0.5)
        del buf
    except MemoryError:
        pass


def _plain(log: list) -> list:
    """Strip the HTML the UI bridge emits - the log is markup, and reading it
    raw hides the one sentence that says why a conversion failed."""
    import re
    out = []
    for row in log:
        t = re.sub(r"<[^>]+>", " ", str(row))
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            out.append(t[:180])
    return out


def _bridge(log: list):
    from converters.post_processing import UIBridge

    class _Sink:
        def __getattr__(self, _n):
            return lambda *a, **k: None
    return UIBridge(header_placeholder=_Sink(), progress_placeholder=_Sink(),
                    metrics_placeholder=_Sink(), log_placeholder=_Sink(),
                    active_file_placeholder=_Sink(), log_lines=log)


def main() -> int:
    if sys.platform != "darwin":
        print("macOS only", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=6)
    ap.add_argument("--kill-at", type=int, default=2,
                    help="kill PowerPoint once this many PDFs exist")
    ap.add_argument("--no-kill", action="store_true", help="control run")
    ap.add_argument("--load", type=int, default=0,
                    help="CPU burners to spin for the duration")
    ap.add_argument("--mem-gb", type=int, default=0,
                    help="GiB of resident memory to hold (transcription is a "
                         "memory event as much as a CPU one)")
    a = ap.parse_args()

    srcs = _samples(a.files)
    if len(srcs) < 2:
        print("not enough .pptx samples under _audit_runs", file=sys.stderr)
        return 2

    work = Path(tempfile.mkdtemp(prefix="cd_crash_"))
    course = work / "Course"
    course.mkdir()
    staged = []
    for i, s in enumerate(srcs):
        d = course / f"Lecture {i + 1}{s.suffix}"
        shutil.copy2(s, d)
        staged.append(d)

    # The user's own document, open and dirty, for the whole run.
    user_doc = work / "MY THESIS DRAFT.pptx"
    shutil.copy2(srcs[0], user_doc)
    _quit()
    _osa(f'tell application "{BUNDLE}" to open POSIX file "{user_doc}"', timeout=120)
    time.sleep(3)
    _osa(f'tell application "{BUNDLE}" to set name of active presentation to '
         f'(name of active presentation)')
    before = _osa(f'tell application "{BUNDLE}" to return (count of presentations)')

    burners, stop = [], None
    if a.load or a.mem_gb:
        import multiprocessing as mp
        stop = mp.Event()
        burners = [mp.Process(target=_burn, args=(stop,)) for _ in range(a.load)]
        if a.mem_gb:
            burners.append(mp.Process(target=_hog, args=(stop, a.mem_gb)))
        for b in burners:
            b.start()
        time.sleep(3 if a.mem_gb else 1)

    killed = {"at": None, "done": False}

    def _killer():
        """Kill PowerPoint the moment the Nth PDF appears - i.e. genuinely
        mid-batch, with a conversion in flight, which is where the matrix
        crash happened."""
        deadline = time.time() + 900
        while time.time() < deadline and not killed["done"]:
            pdfs = len(list(course.glob("*.pdf")))
            if pdfs >= a.kill_at:
                subprocess.run(["pkill", "-x", BUNDLE], capture_output=True)
                killed["at"] = pdfs
                killed["done"] = True
                return
            time.sleep(0.2)

    if not a.no_kill:
        threading.Thread(target=_killer, daemon=True).start()

    # A REAL SyncManager, because `_resolve_conversion_target` reads manifest
    # rows to decide the destination (and the `_NewVersion` protection). The
    # first version of this script passed None and the phase died with
    # "'NoneType' object has no attribute 'local_path'" - which the app
    # isolated correctly, but it measured the rig rather than the product.
    from core.sync_manager import SyncManager
    from converters.post_processing import run_all_conversions
    sm = SyncManager(str(course), 43660, "Course")
    log: list = []
    ui = _bridge(log)
    contract = {"convert_pptx": True}
    t0 = time.time()
    try:
        run_all_conversions(course, sm, contract, ui, course_name="Course",
                            explicit_files=[str(p) for p in staged])
    except Exception as e:
        log.append(f"EXCEPTION {type(e).__name__}: {e}")
    dur = round(time.time() - t0, 1)
    killed["done"] = True

    if stop is not None:
        stop.set()
    for b in burners:
        try:
            b.terminate()
            b.join(timeout=5)
        except Exception:
            pass

    pdfs = sorted(p.name for p in course.glob("*.pdf"))
    left = sorted(p.name for p in course.glob("*.pptx"))
    from converters.verify import pdf_looks_real
    bad = [n for n in pdfs if not pdf_looks_real(course / n)[0]]

    after = _osa(f'tell application "{BUNDLE}" to return (count of presentations)') \
        if _running() else "app not running"
    # NOT `repeat with p in presentations` - that enumeration is measured to
    # fail or hang (see probe_office_document_binding.py), and the first
    # version of this script used it and reported a surviving document as lost.
    # The count is the honest proxy: the user had exactly one document open, so
    # a count that is still >= 1 means nothing closed it.
    user_ok = "1" if (_running() and str(after).isdigit() and int(after) >= 1) else "0"

    result = {
        "files": len(staged),
        "killed_after_n_pdfs": killed["at"],
        "seconds": dur,
        "pdfs_produced": len(pdfs),
        "sources_left": left,
        "unusable_pdfs_left": bad,
        "user_docs_before": before,
        "user_docs_after": after,
        # MEANINGLESS on a kill run, and saying so matters: the pkill that
        # simulates the crash is what closes the user's document, not the app.
        # A real crash does the same (macOS kills the process; PowerPoint's own
        # auto-recovery is what offers the work back). Only the control run can
        # test whether OUR code closes it - and it does not.
        "user_document_survived": (
            "n/a - the injected kill closed it, not the app"
            if killed["at"] is not None else user_ok == "1"),
        "converted_ok": ui.pp_success_count,
        "failed": ui.pp_failure_count,
        "log_tail": _plain(log)[-10:],
    }
    result["VERDICT"] = (
        "RECOVERED - every file converted after the crash"
        if len(pdfs) == len(staged) and not bad
        else f"INCOMPLETE - {len(staged) - len(pdfs)} file(s) never converted"
    )
    print(json.dumps(result, indent=1, ensure_ascii=False))

    _quit()
    shutil.rmtree(work, ignore_errors=True)
    ok = (len(pdfs) == len(staged) and not bad
          and (a.no_kill or killed["at"] is not None))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
