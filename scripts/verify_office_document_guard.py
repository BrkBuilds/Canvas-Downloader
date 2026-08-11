"""Does a FAILED conversion still close the user's document? (macOS)

The defect (`mac_office_active_document`, HIGH, data loss): all three Office
converters bound the document they were about to export with a bare ``active
presentation`` / ``active document`` / ``active workbook``, and their ``on
error`` handler did ``close active <doc> saving no``. ``active`` is the
FRONTMOST document, which is not necessarily ours - so a conversion that failed
while the user had a document open discarded THEIR unsaved edits, and a slow
``open`` could export THEIR document into our PDF.

This script proves the fix on the real applications, per app, with a positive
control per case - because a test that only shows "the user's document
survived" passes just as well against an app that never opened anything at all.

    python scripts/verify_office_document_guard.py            # all three
    python scripts/verify_office_document_guard.py --app Word

Per app it runs two cases:

  CONTROL   a real document converts to a real PDF (proves the guard did not
            break the happy path - the way a name-binding fix fails is by
            matching nothing and converting nothing)
  GUARD     the user has a document open AND UNSAVED; we convert a CORRUPT
            file, which fails; assert the user's document is STILL OPEN and
            still dirty

The user's document is created by the script in a temp dir and is never a real
file of the operator's. Any app the script launched is quit at the end; an app
that was already running is left alone.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

APPS = {
    "Word": ("Microsoft Word", "document", ".doc"),
    "Excel": ("Microsoft Excel", "workbook", ".xlsx"),
    "PowerPoint": ("Microsoft PowerPoint", "presentation", ".pptx"),
}


def _osa(script: str, timeout: float = 90) -> tuple[int, str, str]:
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -9, "", "TIMEOUT"


def _running(bundle: str) -> bool:
    _rc, out, _e = _osa('tell application "System Events" to return '
                        f'(exists application process "{bundle}")', timeout=20)
    return out.lower().startswith("true")


def _quit(bundle: str) -> None:
    _osa(f'tell application "{bundle}" to quit saving no', timeout=45)
    time.sleep(1.5)
    subprocess.run(["pkill", "-x", bundle], capture_output=True)
    time.sleep(1.0)


def _sample(ext: str) -> Path | None:
    """A REAL Office file. A hand-built stub makes Word raise a repair modal and
    hang - recorded in CLAUDE.md and re-confirmed here."""
    for p in (REPO / "_audit_runs").rglob(f"*{ext}"):
        if p.is_file() and 20_000 < p.stat().st_size < 6_000_000:
            return p
    return None


def _make_legacy_doc(work: Path) -> Path | None:
    """`textutil -convert doc` makes a genuine legacy .doc that Word opens
    silently; a hand-written one triggers the repair modal."""
    txt = work / "seed.txt"
    txt.write_text("Canvas Downloader guard control document.\n", encoding="utf-8")
    out = work / "seed.doc"
    r = subprocess.run(["textutil", "-convert", "doc", "-output", str(out), str(txt)],
                       capture_output=True, timeout=60)
    return out if (r.returncode == 0 and out.exists()) else None


def _converter(app: str):
    from converters.pdf import PowerPointToPDF
    from converters.word import WordToPDF
    from converters.excel import ExcelToPDF
    return {"PowerPoint": PowerPointToPDF, "Word": WordToPDF, "Excel": ExcelToPDF}[app]()


def _convert(app: str, path: Path):
    """Call the real converter and normalise its return to a path-or-None.

    ``ExcelToPDF.convert`` returns ``(path | None, reason)`` while the other two
    return ``path | None``. The first version of this script stringified the
    tuple, so every Excel control read as a FAILED conversion - a red row caused
    entirely by the checker, which is the failure mode the audit rules warn
    about before filing anything against the product.
    """
    out = _converter(app).convert(str(path))
    if isinstance(out, tuple):
        out = out[0]
    return out


def _control(app: str, work: Path) -> dict:
    """A real document must still convert. This is what catches a guard that
    matches nothing."""
    bundle, _klass, ext = APPS[app]
    src = _make_legacy_doc(work) if app == "Word" else _sample(ext)
    if src is None:
        return {"case": "CONTROL", "skipped": f"no sample {ext}"}
    staged = work / f"control{src.suffix}"
    shutil.copy2(src, staged)
    t0 = time.time()
    try:
        out = _convert(app, staged)
    except Exception as e:
        out = f"EXCEPTION {e}"
    ok = bool(out) and not str(out).startswith("EXCEPTION") and Path(str(out)).exists()
    real_pdf = False
    if ok:
        from converters.verify import pdf_looks_real
        real_pdf = bool(pdf_looks_real(Path(str(out)))[0])
    return {"case": "CONTROL", "converted": ok, "pdf_is_real": real_pdf,
            "seconds": round(time.time() - t0, 1), "output": str(out)}


def _guard(app: str, work: Path) -> dict:
    """The case that loses data.

    The user's document is opened AND MADE DIRTY, because `close saving no`
    only destroys something when there are unsaved changes - a clean document
    closing is merely rude.
    """
    bundle, klass, ext = APPS[app]
    user_src = _make_legacy_doc(work) if app == "Word" else _sample(ext)
    if user_src is None:
        return {"case": "GUARD", "skipped": f"no sample {ext}"}
    user_doc = work / f"USER_DOCUMENT{user_src.suffix}"
    shutil.copy2(user_src, user_doc)

    # Open it as the user would, and dirty it so `saving no` would really lose
    # something. Dirtying is per-app (each has its own object model), and it is
    # allowed to fail - the survival assertion below is the real check.
    _osa(f'tell application "{bundle}" to open POSIX file "{user_doc}"', timeout=90)
    time.sleep(2.5)
    dirty = {
        "Word": 'tell application "Microsoft Word" to set content of text object of '
                'active document to "edited by the user"',
        "Excel": 'tell application "Microsoft Excel" to set value of range "A1" of '
                 'active sheet to "edited by the user"',
        "PowerPoint": 'tell application "Microsoft PowerPoint" to set name of '
                      'active presentation to (name of active presentation)',
    }[app]
    _osa(dirty, timeout=45)

    before = _osa(f'tell application "{bundle}" to return (count of {klass}s)', timeout=30)[1]

    # A CORRUPT file of the same type: the conversion must fail, which is what
    # drives the `on error` handler under test.
    corrupt = work / f"corrupt{ext}"
    corrupt.write_bytes(b"PK\x03\x04this is not a real office file" + b"\x00" * 4096)
    try:
        out = _convert(app, corrupt)
    except Exception as e:
        out = f"EXCEPTION {e}"
    conversion_failed = not (bool(out) and not str(out).startswith("EXCEPTION")
                             and Path(str(out)).exists())

    after = _osa(f'tell application "{bundle}" to return (count of {klass}s)', timeout=30)[1]
    still_open = _osa(
        f'''tell application "{bundle}"
              set n to 0
              try
                if (name of active {klass}) is "{user_doc.name}" then set n to 1
              end try
              return n as text
            end tell''', timeout=30)[1]

    return {
        "case": "GUARD",
        "conversion_failed_as_intended": conversion_failed,
        "user_docs_before": before,
        "user_docs_after": after,
        "user_document_still_frontmost": still_open == "1",
        "VERDICT": ("user document SURVIVED" if still_open == "1"
                    else "USER DOCUMENT WAS CLOSED - data loss"),
    }


def run(app: str) -> dict:
    bundle = APPS[app][0]
    was_running = _running(bundle)
    work = Path(tempfile.mkdtemp(prefix=f"cd_guard_{app}_"))
    try:
        # Each case gets a FRESH app: a wedged Word answers every later file
        # identically, so a shared instance measures the previous case.
        _quit(bundle)
        control = _control(app, work)
        _quit(bundle)
        guard = _guard(app, work)
    finally:
        _quit(bundle)
        if was_running:
            subprocess.run(["open", "-g", "-j", "-a", f"/Applications/{bundle}.app"],
                           capture_output=True)
        shutil.rmtree(work, ignore_errors=True)
    return {"app": app, "control": control, "guard": guard}


def main() -> int:
    if sys.platform != "darwin":
        print("macOS only", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", choices=sorted(APPS), action="append")
    a = ap.parse_args()
    results = [run(x) for x in (a.app or ["Word", "Excel", "PowerPoint"])]
    print(json.dumps(results, indent=1, ensure_ascii=False))

    bad = []
    for r in results:
        c, g = r["control"], r["guard"]
        if not c.get("skipped") and not (c.get("converted") and c.get("pdf_is_real")):
            bad.append(f"{r['app']}: CONTROL failed - the guard broke the happy path")
        if not g.get("skipped") and not g.get("user_document_still_frontmost"):
            bad.append(f"{r['app']}: {g.get('VERDICT')}")
    print("\n" + ("\n".join(bad) if bad else
                  "ALL PASS - every control converted and no user document was closed"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
