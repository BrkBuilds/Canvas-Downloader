"""The finding register - one durable, editable list of what the audit found.

A run's ``findings.jsonl`` is evidence: it belongs to that run and is never
edited. This is the other half - a **cumulative** register you can actually work
from, checked into the repo, where each finding keeps a status you set by hand
and the next audit updates the facts around it without touching your decision.

The problem it solves: a per-run report is useless as a work queue. Run the
audit twice and you have two reports, both listing the same twelve things, with
no way to tell which you already triaged. So findings are keyed by a
**fingerprint** derived from what makes them the same defect - category plus the
shape of the title, with the run-specific numbers stripped out. "7 source files
survived conversion" and "9 source files survived conversion" are one entry
whose count changed, not two findings.

Status is owned by the human and never overwritten:

    open        needs a decision
    fixed       code changed; the next run should stop reporting it
    accepted    real, deliberate, not worth changing - stop asking
    wontfix     understood and declined
    invalid     the audit was wrong; fix the check, not the app

Anything marked ``fixed`` that shows up again is called out as a REGRESSION,
which is the single most valuable line the register produces.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .findings import SEV_RANK, Ledger

REGISTER_PATH = Path(__file__).resolve().parents[1] / "AUDIT_FINDINGS.md"

STATUSES = ("open", "fixed", "accepted", "wontfix", "invalid")
CLOSED = ("fixed", "accepted", "wontfix", "invalid")

_FP = re.compile(r"<!--\s*fp:([0-9a-f]{12})\s*-->")
_FIELD = re.compile(r"^\*\*(Status|Severity|Category|Oracles|First seen|Last seen|"
                    r"Occurrences|Scenario|Course)\*\*:\s*(.*)$", re.M)
_HEADING = re.compile(r"^### .*$", re.M)
_STALE_MARK = "> Not observed in the latest run."
_STALE_RE = re.compile(r"^[ \t]*" + re.escape(_STALE_MARK) + r"[ \t]*$\n?", re.M)


def fingerprint(f: dict) -> str:
    """Stable identity for "the same defect", independent of run-specific counts.

    Numbers are stripped because they are the part that legitimately varies
    between runs (7 files today, 9 next week), and paths are stripped because
    the same defect surfaces on different courses. What is left - the category
    and the sentence shape - is what a human would call "the same problem".
    """
    import hashlib
    title = f.get("title", "")
    title = re.sub(r"\d+", "N", title)
    title = re.sub(r"['\"][^'\"]{4,}['\"]", "X", title)
    title = re.sub(r"\s+", " ", title).strip().lower()
    key = f"{f.get('category', '')}|{title}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------

def parse(path: Path = REGISTER_PATH) -> dict[str, dict]:
    """Read the existing register, preserving hand-written status and notes."""
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    entries: dict[str, dict] = {}
    blocks = _split_blocks(text)
    for block in blocks:
        m = _FP.search(block)
        if not m:
            continue
        fp = m.group(1)
        fields = {k.lower().replace(" ", "_"): v.strip()
                  for k, v in _FIELD.findall(block)}
        title_m = re.search(r"^###\s+(.*)$", block, re.M)
        entries[fp] = {**_fields_to_entry(fp, fields, title_m, block)}
    return entries


def _read_notes(block: str) -> str:
    """The human's own notes, and ONLY those.

    Parsed up to the entry's ``---`` separator rather than to the end of the
    block, and with the renderer's "Not observed" marker removed. Both matter
    because parse and render are a LOOP: whatever this returns is written back
    out, so anything it wrongly swallows is re-emitted, swallowed again next
    run, and grows. That is not hypothetical - it shipped, and one entry
    accumulated four copies of the separator and the stale marker inside its
    own Notes field before the next render.
    """
    parts = block.split("**Notes**:", 1)
    if len(parts) != 2:
        return ""
    body = _STALE_RE.sub("", parts[1])
    out = []
    for line in body.splitlines():
        if line.strip() == "---":
            break
        out.append(line)
    return "\n".join(out).strip()


def _fields_to_entry(fp, fields, title_m, block) -> dict:
    return {
        "fp": fp,
        "title": (title_m.group(1).strip() if title_m else "").lstrip("~ ").strip(),
        "status": (fields.get("status") or "open").lower(),
        "severity": fields.get("severity", "medium"),
        "category": fields.get("category", "observation"),
        "oracles": fields.get("oracles", "").replace("—", "").strip(),
        "first_seen": fields.get("first_seen", ""),
        "last_seen": fields.get("last_seen", ""),
        "occurrences": _int(fields.get("occurrences"), 1),
        "scenario": fields.get("scenario", ""),
        "notes": _read_notes(block),
        "detail": _extract_detail(block),
    }


def _split_blocks(text: str) -> list[str]:
    idxs = [m.start() for m in _HEADING.finditer(text)]
    return [text[a:b] for a, b in zip(idxs, idxs[1:] + [len(text)])]


def _extract_detail(block: str) -> str:
    m = re.search(r"\*\*Detail\*\*:\s*\n(.*?)(?=\n\*\*|\Z)", block, re.S)
    return m.group(1).strip() if m else ""


def _run_of(seen: str) -> str:
    """The run id out of a "2026-07-28 (20260728_010431_phase2_real)" stamp.

    Run ids begin with a timestamp, so a plain string comparison orders them -
    which is all "is this run newer than the one that closed it" needs.
    """
    m = re.search(r"\(([^)]+)\)\s*$", seen.strip())
    return m.group(1) if m else ""


def _int(v, default):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------

def update(run_findings: list[dict], run_id: str,
           path: Path = REGISTER_PATH) -> dict:
    """Merge one run's findings into the register. Never edits a status."""
    existing = parse(path)
    today = date.today().isoformat()
    seen, new, regressed, reopened = set(), [], [], []

    for f in run_findings:
        if f.get("category") == "observation":
            continue                     # context, not a work item
        fp = fingerprint(f)
        seen.add(fp)
        prev = existing.get(fp)
        if prev is None:
            existing[fp] = {
                "fp": fp, "title": f.get("title", ""),
                "status": "open",
                "severity": f.get("severity", "medium"),
                "category": f.get("category", "observation"),
                "oracles": ",".join(f.get("oracles", [])),
                "first_seen": f"{today} ({run_id})",
                "last_seen": f"{today} ({run_id})",
                "occurrences": 1,
                "detail": f.get("detail", ""),
                "notes": "",
                "scenario": f.get("scenario", ""),
                "course": f.get("course", ""),
            }
            new.append(fp)
        else:
            # Facts refresh; the human's status and notes never do.
            was = prev["status"]
            # A finding is only a REGRESSION if it reappears in a run LATER than
            # the one it was closed in. Without this, closing something
            # mid-audit and re-running `register update` against the same
            # (unchanged) ledger reports the fix as a regression immediately -
            # the run's findings file is cumulative, so the entry is still in
            # it. One false regression is enough to make the whole signal
            # ignorable, and this is the signal the register exists for.
            # A regression means the defect came BACK - it reappeared in a run
            # LATER than the one that closed it. Merging an older or equal run
            # says nothing: a run's findings file is cumulative, so fixing
            # something mid-audit and re-merging the same ledger finds it still
            # there, and re-checking a folder after a fix re-reads the pre-fix
            # pass. Both reported a fix as a regression, and one false regression
            # is enough to make the whole signal ignorable - which is the one
            # signal this register exists to produce.
            prev_run = _run_of(prev.get("last_seen", ""))
            same_run = prev.get("closed_in_run") == run_id or \
                (prev_run and run_id <= prev_run)
            prev.update({
                "title": f.get("title", prev["title"]),
                "severity": f.get("severity", prev["severity"]),
                "oracles": ",".join(f.get("oracles", [])) or prev.get("oracles", ""),
                "last_seen": f"{today} ({run_id})",
                "occurrences": prev.get("occurrences", 1) + 1,
                "detail": f.get("detail") or prev.get("detail", ""),
                "scenario": f.get("scenario", prev.get("scenario", "")),
                "course": f.get("course", prev.get("course", "")),
            })
            if same_run:
                pass          # closed during this very run; not evidence of anything
            elif was == "fixed":
                regressed.append(fp)
            elif was in CLOSED:
                reopened.append(fp)

    render(existing, path, run_id, seen)
    return {
        "register": str(path),
        "total": len(existing),
        "new": len(new),
        "regressions": [existing[fp]["title"] for fp in regressed],
        "closed_but_seen_again": [existing[fp]["title"] for fp in reopened],
        "open": sum(1 for e in existing.values() if e["status"] == "open"),
        "by_status": _tally(e["status"] for e in existing.values()),
    }


def render(entries: dict[str, dict], path: Path, run_id: str,
           seen_this_run: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(entries.values(),
                  key=lambda e: (e["status"] != "open",
                                 SEV_RANK.get(e["severity"], 9),
                                 e["category"], e["title"]))
    open_rows = [e for e in rows if e["status"] == "open"]

    out = [
        "# Audit findings register",
        "",
        "Cumulative work list produced by the live audit (`/audit-live`, or",
        "`python -m tests.audit`). **This file is meant to be edited by hand.**",
        "",
        "Set `**Status**` on any entry to one of `open`, `fixed`, `accepted`,",
        "`wontfix`, `invalid`, and add anything you like under `**Notes**`. The",
        "audit refreshes the facts around your decision on every run and never",
        "overwrites it. Anything you marked `fixed` that appears again is",
        "reported as a **regression** — that is the line worth watching.",
        "",
        f"Last updated by run `{run_id}` on {date.today().isoformat()}.",
        "",
        # "open" is stated once, in bold, because it is the number anybody
        # reading this file is here for. Listing it again in the tally made the
        # header read "4 open · 28 total · 9 fixed · 15 invalid · 4 open".
        f"**{len(open_rows)} open** · {len(rows)} total · "
        + " · ".join(f"{n} {s}" for s, n in
                     sorted(_tally(e["status"] for e in rows).items())
                     if s != "open"),
        "",
        "---",
        "",
    ]

    for e in rows:
        closed = e["status"] in CLOSED
        title = f"~~{e['title']}~~" if closed else e["title"]
        stale = "" if e["fp"] in seen_this_run else f"  \n{_STALE_MARK}"
        out += [
            f"### {title}",
            f"<!-- fp:{e['fp']} -->",
            "",
            f"**Status**: {e['status']}",
            f"**Severity**: {e['severity']}",
            f"**Category**: {e['category']}",
            f"**Oracles**: {e.get('oracles', '') or '—'}",
            f"**First seen**: {e['first_seen']}",
            f"**Last seen**: {e['last_seen']}",
            f"**Occurrences**: {e['occurrences']}",
        ]
        if e.get("course") or e.get("scenario"):
            out.append(f"**Scenario**: {e.get('scenario', '')} "
                       f"{('· ' + e['course']) if e.get('course') else ''}".strip())
        if e.get("detail"):
            out += ["", "**Detail**:", "", e["detail"]]
        out += ["", f"**Notes**: {e.get('notes', '')}{stale}", "", "---", ""]

    path.write_text("\n".join(out), encoding="utf-8")


def update_from_run(rp, path: Path = REGISTER_PATH) -> dict:
    return update(Ledger(rp.findings).all(), rp.run_id, path)


def _tally(items) -> dict:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items()))
