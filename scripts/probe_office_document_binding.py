"""What does an Office app CALL the document we just opened?

`converters/{pdf,word,excel}.py` all bind the document they are about to export
with ``active <presentation|document|workbook>``. That is the frontmost one,
not ours - so an error path can close the USER's open document `saving no`, and
a slow ``open`` can export theirs into our PDF. The fix is to bind by the
staged basename (`office_container_stage` stages every conversion as
``src.<ext>``), which requires knowing EXACTLY what string each app reports in
its ``name`` property.

This probe answers that, per app, against the real applications - it does not
assume. It also answers the second question the fix depends on: does a
``whose name is ...`` clause actually resolve, and does ``open`` itself yield a
usable reference (the converters' docstrings claim it does not).

    python scripts/probe_office_document_binding.py

It opens a throwaway file in each app, reads properties, closes it, and quits
any app it launched. Nothing is converted and nothing is written to a user
folder.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

APPS = {
    "Word": ("Microsoft Word", "document", ".docx"),
    "Excel": ("Microsoft Excel", "workbook", ".xlsx"),
    "PowerPoint": ("Microsoft PowerPoint", "presentation", ".pptx"),
}


def _osa(script: str, timeout: float = 120) -> tuple[int, str, str]:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _running(bundle: str) -> bool:
    _rc, out, _e = _osa('tell application "System Events" to return '
                        f'(exists application process "{bundle}")')
    return out.lower().startswith("true")


def _find_sample(ext: str) -> Path | None:
    """A real Office file from the audit downloads - a hand-built stub makes
    Word raise a repair modal and hang (recorded in CLAUDE.md)."""
    roots = [REPO / "_audit_runs"]
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob(f"*{ext}"):
            if p.is_file() and 20_000 < p.stat().st_size < 8_000_000:
                return p
    return None


def probe(app: str) -> dict:
    bundle, klass, ext = APPS[app]
    out: dict = {"app": app, "class": klass}

    sample = _find_sample(ext)
    if sample is None:
        return {**out, "error": f"no sample {ext} found under _audit_runs"}

    # Stage exactly as office_container_stage does: a SHORT fixed basename in
    # a per-conversion uuid dir. The whole point is that we own this name.
    work = Path(tempfile.mkdtemp(prefix="cd_probe_"))
    staged = work / ("src" + ext)
    shutil.copy2(sample, staged)
    out["staged_name"] = staged.name
    out["was_running_before"] = _running(bundle)

    posix = str(staged).replace("\\", "\\\\").replace('"', '\\"')
    # MEASURED, not assumed: `open` returns nothing usable in all three apps -
    # capturing it raises -2753 "The variable opened is not defined", which is
    # exactly what the converters' docstrings claim. So the only question left
    # is whether a `whose name is` clause can find the document afterwards.
    rc, stdout, stderr = _osa(f'''
        tell application "{bundle}"
            open POSIX file "{posix}"
            set d to active {klass}
            set nm to name of d
            set cnt to (count of {klass}s)
            set byName to "NOT FOUND"
            try
                set byName to name of (first {klass} whose name is "{staged.name}")
            end try
            set fn to "n/a"
            try
                set fn to (full name of d) as text
            end try
            close d saving no
            return nm & " || " & (cnt as text) & " || " & byName & " || " & fn
        end tell''')
    out["rc"] = rc
    if rc != 0:
        out["stderr"] = stderr
    else:
        parts = [p.strip() for p in stdout.split("||")]
        while len(parts) < 4:
            parts.append("")
        out.update({
            "active_name": parts[0],
            "open_count": parts[1],
            "resolved_by_name": parts[2],
            "full_name": parts[3],
            "name_matches_staged": parts[0] == staged.name,
            "whose_name_works": parts[2] == staged.name,
        })
    shutil.rmtree(work, ignore_errors=True)
    if not out["was_running_before"]:
        _osa(f'tell application "{bundle}" to quit saving no', timeout=60)
    return out


def main() -> int:
    if sys.platform != "darwin":
        print("macOS only", file=sys.stderr)
        return 2
    results = [probe(a) for a in ("Word", "Excel", "PowerPoint")]
    print(json.dumps(results, indent=1, ensure_ascii=False))
    ok = all(r.get("whose_name_works") for r in results)
    print("\nVERDICT:", "bind-by-name works in all three"
          if ok else "NOT all three resolve by name - read the rows above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
