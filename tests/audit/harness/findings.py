"""What the audit found, and how sure it is.

A finding is an OBSERVED DISAGREEMENT, and it always names the two views that
disagree. That framing is the whole discipline of this suite: "the sync review
looked wrong" is an opinion, while "O1 shows this file under New Files, O4 has a
manifest row for it whose local_path exists on disk with a matching md5" is a
defect with a reproduction attached.

Severity is about consequence to the user, never about how hard it was to spot:

    critical  data loss, or a wrong file delivered and presented as correct
    high      a file that should exist does not, or is silently mis-categorised
    medium    the app tells the user something untrue, but the files are right
    low       cosmetic or recoverable; a power user would shrug
    info      an observation worth recording that is not itself wrong

``synthetic`` marks findings whose precondition was fabricated by the seeder
rather than produced by Canvas. Those still exercise the real code path - the
analyzer compares live Canvas metadata against manifest rows, so forging the
manifest side forges exactly the same comparison - but the flag is kept so a
reader always knows which findings rest on a fixture.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

SEVERITIES = ("critical", "high", "medium", "low", "info")
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}

CATEGORIES = (
    "discovery",            # a file that exists on Canvas was never found
    "delivery",             # found but not written, or written wrong/corrupt
    "placement",            # right file, wrong folder or wrong name
    "classification",       # wrong sync category
    "persistence",          # manifest/contract/state written wrong
    "ui-truth",             # the screen contradicts reality or itself
    "conversion",           # post-processing produced nothing / the wrong thing
    "panopto",              # recordings, transcription
    "config",               # a setting the user chose did not take effect
    "robustness",           # crash, traceback, hang, leftover artifact
    "regression-guard",     # an invariant this project has broken before
    "observation",          # context, not a defect
)


@dataclass
class Finding:
    title: str
    severity: str = "medium"
    category: str = "observation"
    oracles: tuple[str, ...] = ()
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    scenario: str = ""
    course: str = ""
    step: str = ""
    synthetic: bool = False
    # Which check produced this, as "<suite>@<folder>". A re-check of the same
    # folder by the same suite SUPERSEDES the earlier verdict - see
    # Ledger.supersede.
    origin: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise ValueError(f"bad severity {self.severity!r}; use one of {SEVERITIES}")
        if self.category not in CATEGORIES:
            raise ValueError(f"bad category {self.category!r}; use one of {CATEGORIES}")

    def as_dict(self) -> dict:
        d = asdict(self)
        d["oracles"] = list(self.oracles)
        return d


class Ledger:
    """Append-only findings file for one run.

    Append-only on purpose: a long audit is interrupted, resumed, and re-run in
    parts, and a ledger that is rewritten wholesale loses everything recorded
    before the step that crashed - which is usually the step that mattered.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, f: Finding) -> Finding:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(f.as_dict(), ensure_ascii=False, default=str) + "\n")
        return f

    def extend(self, findings, origin: str = "") -> list[Finding]:
        if origin:
            for f in findings:
                f.origin = origin
            self.supersede(origin)
        out = []
        for f in findings:
            out.append(self.add(f))
        return out

    def supersede(self, origin: str) -> int:
        """Retire the previous verdict from the same check on the same folder.

        A check is a MEASUREMENT, re-derived from the folder every time it runs.
        Run it twice and the second result is simply the truth about that folder;
        the first is stale by construction. Keeping both made a fixed problem
        look unfixed - re-checking after a repair left the pre-repair findings in
        the ledger, the register saw them, and the repair was reported as still
        broken. That happened three times before this existed, and each time the
        cleanup was by hand.

        Superseded lines are rewritten with ``superseded: true`` rather than
        deleted, so the evidence of what the earlier pass said survives for
        anyone reading the file directly. The ledger stays append-only in spirit:
        nothing is lost, only demoted.
        """
        if not self.path.is_file():
            return 0
        rows, changed = [], 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                rows.append(line)
                continue
            if r.get("origin") == origin and not r.get("superseded"):
                r["superseded"] = True
                changed += 1
            rows.append(json.dumps(r, ensure_ascii=False, default=str))
        if changed:
            self.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return changed

    def all(self, include_superseded: bool = False) -> list[dict]:
        if not self.path.is_file():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("superseded") and not include_superseded:
                    continue
                rows.append(r)
        return rows

    def summary(self) -> dict:
        rows = self.all()
        by_sev: dict[str, int] = {s: 0 for s in SEVERITIES}
        by_cat: dict[str, int] = {}
        for r in rows:
            by_sev[r.get("severity", "medium")] = by_sev.get(r.get("severity", "medium"), 0) + 1
            c = r.get("category", "observation")
            by_cat[c] = by_cat.get(c, 0) + 1
        real = [r for r in rows if r.get("category") != "observation"]
        return {
            "total": len(rows),
            "defects": len(real),
            "by_severity": by_sev,
            "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
            "blocking": by_sev.get("critical", 0) + by_sev.get("high", 0),
        }

    def ranked(self, limit: int | None = None) -> list[dict]:
        rows = sorted(self.all(),
                      key=lambda r: (SEV_RANK.get(r.get("severity", "medium"), 9),
                                     r.get("category", ""), r.get("title", "")))
        return rows[:limit] if limit else rows


# -- convenience constructors used all over crosscheck.py -------------------

def disagreement(a: str, b: str, title: str, *, severity: str, category: str,
                 detail: str = "", **kw) -> Finding:
    """A finding phrased as "view A and view B do not agree"."""
    return Finding(title=title, severity=severity, category=category,
                   oracles=(a, b), detail=detail, **kw)


def observation(title: str, detail: str = "", **kw) -> Finding:
    return Finding(title=title, severity="info", category="observation",
                   detail=detail, **kw)
