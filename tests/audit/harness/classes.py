"""Group findings into CLASSES, and diff two sets of them.

Triaging a matrix one finding at a time does not scale and does not work: 350
findings across 73 rows are not 350 problems, they are a dozen problems with a
row number attached. What a reader needs is the dozen.

A **class** is a finding's title with everything row-specific removed - the
quoted filenames, the counts, the sizes, the course ids. Two findings in the
same class have the same cause; the count tells you how far it reaches and the
scenario list tells you where to reproduce it.

The diff is the reason this module exists rather than a shell one-liner. The
README names comparing two runs by CLASS as one of only three techniques that
reliably find checker defects, and it is the one that cannot be improvised
mid-triage: a class that appears or vanishes with no product change between the
two runs is the checker moving, not the app. Both sides of that comparison have
to normalise identically or the diff is noise, which is exactly what an ad-hoc
regex per session produces.

The normalisation is deliberately AGGRESSIVE. A class that merges two genuinely
different causes is visible the moment you read its scenario list and open one;
a class that splits one cause across forty rows hides it, which is the failure
this is built to prevent.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

# Order matters: quoted spans are blanked before numbers, so a filename holding
# digits collapses to one placeholder instead of leaving a trail of `N`s that
# would split the class by how many digits its filename happened to contain.
_SUBS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"'[^']*'"), "'X'"),
    (re.compile(r'"[^"]*"'), '"X"'),
    (re.compile(r"\b\d[\d_,.]*\s*(?:MB|KB|GB|B|%|s|ms)\b", re.I), "N"),
    (re.compile(r"\b\d[\d_,.]*\b"), "N"),
    # Only the English pluralisation, and only that. The first version of this
    # dropped ANY trailing parenthetical on the theory that it named the
    # instance - measured against all 1,764 titles the corpus holds, it fired
    # 68 times on "(s)" and 3 times on something that carried meaning: a course
    # code, and "(36 recordings expected)". So the general rule bought nothing
    # and its only real effect would have been to merge "X failed (transient)"
    # into "X failed" - two causes in one class, the failure this module exists
    # to avoid. Collapsing "error(s)" and "errors" together is still worth
    # doing: both phrasings are in use for the same finding.
    (re.compile(r"\(s\)"), "s"),
    (re.compile(r"\s+"), " "),
)

# Applied for GROUPING only, never for display. "1 file" and "4 files" are one
# cause, but collapsing just the digit leaves "N file" beside "N files" - the
# class SPLITS on whether the run happened to find exactly one of something,
# which is the failure this module exists to prevent. Scoped to the word right
# after a count so it cannot reach a noun that is plural for its own reasons.
#
# It mangles stems - "N Canvas files" keys as "N Canva file" - and that is
# precisely why it is kept out of the label. Grouping only has to be CONSISTENT;
# a label has to be readable, and a triage table that says "N Canva files" reads
# as a typo and spends the reader's confidence. Swept over the 210 distinct
# titles this project has produced, it merges 0 classes today: it guards a
# LATENT split, so do not delete it as dead weight - "finished with 1 error" is
# one unlucky run away.
_KEY_SUBS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bN (\w+?)s\b"), r"N \1"),
    # ...and the verb that agrees with it. Handling the noun alone leaves the
    # split half-fixed: "1 file was downloaded twice" and "6 files were
    # downloaded twice" are one cause, and collapsing only the noun still keeps
    # them apart on was/were. Anchored to the position right after a count, so
    # it cannot reach a verb elsewhere in the sentence.
    (re.compile(r"\bN (\w+) were\b"), r"N \1 was"),
    (re.compile(r"\bN (\w+) are\b"), r"N \1 is"),
    (re.compile(r"\bN (\w+) have\b"), r"N \1 has"),
)


def classify(title: str) -> str:
    """The row-independent shape of a finding title, as a human should read it."""
    out = title or ""
    for pat, rep in _SUBS:
        out = pat.sub(rep, out)
    return out.strip()


def class_key(title: str) -> str:
    """What decides whether two findings are the same class.

    Strictly coarser than `classify`: everything that separates two classes here
    separates them there too, so a label can never span two keys.
    """
    out = classify(title)
    for pat, rep in _KEY_SUBS:
        out = pat.sub(rep, out)
    return out.strip()


def load(path: str | Path) -> list[dict]:
    """Findings from a .jsonl ledger. A malformed line is skipped, not fatal -
    a truncated final line is what a killed worker leaves behind, and refusing
    to read the other 300 findings because of it helps nobody."""
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def group(findings: list[dict], *, include_info: bool = True) -> list[dict]:
    """Findings folded into classes, worst severity first then widest reach.

    A class keeps the WORST severity seen in it, never the first or the most
    common: severity is about consequence, so a class that is critical on one
    row and medium on thirty is a critical class with thirty instances.
    """
    from .findings import SEV_RANK

    buckets: dict[tuple[str, str], dict] = {}
    for f in findings:
        sev = f.get("severity", "medium")
        cat = f.get("category", "observation")
        if not include_info and (sev == "info" or cat == "observation"):
            continue
        title = f.get("title", "")
        key = (cat, class_key(title))
        b = buckets.setdefault(key, {
            "category": cat, "key": key[1], "severity": sev, "count": 0,
            "scenarios": set(), "lanes": set(), "titles": set(),
            "labels": Counter(), "fps": set()})
        b["labels"][classify(title)] += 1
        b["count"] += 1
        try:
            from .register import fingerprint
            b["fps"].add(fingerprint(f))
        except Exception:
            pass
        if SEV_RANK.get(sev, 9) < SEV_RANK.get(b["severity"], 9):
            b["severity"] = sev
        if f.get("scenario"):
            b["scenarios"].add(f["scenario"])
        if f.get("lane"):
            b["lanes"].add(f["lane"])
        b["titles"].add(f.get("title", ""))

    rows = []
    for b in buckets.values():
        # The label is the most common readable form in the bucket, tie-broken
        # alphabetically so two runs with the same content always render the
        # same string - a diff that reported a class as gone+appeared because
        # its label flickered would be pure noise.
        label = min(b["labels"].most_common(),
                    key=lambda kv: (-kv[1], kv[0]))[0] if b["labels"] else b["key"]
        rows.append({
            "severity": b["severity"], "category": b["category"],
            "class": label, "key": b["key"], "count": b["count"],
            "rows": len(b["scenarios"]),
            "scenarios": sorted(b["scenarios"])[:8],
            "lanes": sorted(b["lanes"]),
            "example": sorted(b["titles"])[0] if b["titles"] else "",
            "_fingerprints": sorted(b["fps"]),
        })
    rows.sort(key=lambda r: (SEV_RANK.get(r["severity"], 9), -r["count"],
                             r["category"], r["key"]))
    return rows


def diff(before: list[dict], after: list[dict], *,
         include_info: bool = True) -> dict:
    """What changed between two sets of findings, BY CLASS.

    Three buckets, and the middle one is the point:

    * ``gone``      - a class in ``before`` and not in ``after``
    * ``appeared``  - a class in ``after`` and not in ``before``
    * ``changed``   - a class in both whose count moved

    With no product change between the two, every entry here is the checker.
    With a product change, this says which classes it touched and whether it
    touched anything it should not have.
    """
    # Keyed on `key`, never on the displayed label - the label is chosen by
    # majority within a bucket, so it can legitimately differ between two runs
    # holding the same class, and keying on it would report that class as gone
    # AND appeared.
    a = {(r["category"], r["key"]): r for r in group(before, include_info=include_info)}
    b = {(r["category"], r["key"]): r for r in group(after, include_info=include_info)}

    gone = [a[k] for k in a.keys() - b.keys()]
    appeared = [b[k] for k in b.keys() - a.keys()]
    changed = [{**b[k], "was": a[k]["count"], "now": b[k]["count"],
                "delta": b[k]["count"] - a[k]["count"]}
               for k in a.keys() & b.keys() if a[k]["count"] != b[k]["count"]]

    from .findings import SEV_RANK
    key = lambda r: (SEV_RANK.get(r["severity"], 9), -r["count"])  # noqa: E731
    return {
        "before_total": sum(r["count"] for r in a.values()),
        "after_total": sum(r["count"] for r in b.values()),
        "before_classes": len(a), "after_classes": len(b),
        "gone": sorted(gone, key=key),
        "appeared": sorted(appeared, key=key),
        "changed": sorted(changed, key=lambda r: (SEV_RANK.get(r["severity"], 9),
                                                  -abs(r["delta"]))),
    }


def annotate_with_register(rows: list[dict]) -> list[dict]:
    """Tag each class with what the register already knows about it.

    This is the question that costs the most time in triage and it has an
    answer sitting on disk: *has this been seen before, and was it already
    dealt with?* On 2026-07-29 it took an hour of reading source and git state
    to work out that six of seven surviving classes were defects fixed earlier
    the same session, whose evidence was merely product-stale - and the
    register had said so all along, under differently-worded titles.

    A class inherits the status of the register entry its findings fingerprint
    to, so ``fixed`` means "already dealt with; this evidence predates the fix"
    and ``new`` means the audit has genuinely not seen it before. Findings that
    disagree are reported as ``mixed`` rather than silently taking the first -
    the register fingerprint is coarser than a class key, so one class CAN span
    two entries, and picking one would hide the other.
    """
    try:
        from . import register as reg
        entries = reg.parse(reg.REGISTER_PATH)
    except Exception:
        return rows                       # never let triage die on a bad register

    for r in rows:
        statuses = {
            entries[fp]["status"]
            for fp in r.get("_fingerprints", ())
            if fp in entries
        }
        if not statuses:
            r["register"] = "new"
        elif len(statuses) == 1:
            r["register"] = statuses.pop()
        else:
            r["register"] = "mixed:" + "/".join(sorted(statuses))
        r.pop("_fingerprints", None)
    return rows


def lane_sources(parent_root: Path, *, rechecked: bool) -> list[tuple[str, Path]]:
    """(lane, findings path) for every lane of a matrix run.

    Reads ``lanes.json`` rather than globbing ``*__*`` directories, so a lane
    that was planned but produced no file is still listed - and therefore still
    reported as missing instead of silently lowering the total.
    """
    plan_path = Path(parent_root) / "lanes.json"
    if not plan_path.is_file():
        return []
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    name = "findings.rechecked.jsonl" if rechecked else "findings.jsonl"
    out = []
    for lane in plan.get("lanes", []):
        out.append((lane["lane"],
                    Path(parent_root).parent / lane["run_id"] / name))
    return out


def collect_lanes(parent_root: Path, *, rechecked: bool) -> tuple[list[dict], list[str]]:
    """Every lane's findings, each tagged with its lane, plus the lanes missing.

    Tagging happens here because ``lane`` is what separates a resource clash
    from a product defect: a class confined to the ``office`` lane is a
    statement about Excel, not about the app.
    """
    rows, missing = [], []
    for lane, path in lane_sources(parent_root, rechecked=rechecked):
        if not path.is_file():
            missing.append(lane)
            continue
        for f in load(path):
            f["lane"] = lane
            rows.append(f)
    return rows, missing
