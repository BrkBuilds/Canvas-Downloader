"""Redact personal data from audit artifacts before they are committed.

`_audit_runs/` is tracked for its RESULT - findings, reports, debug logs, the
health log - because that is what a later session re-reads to adjudicate a
finding, and losing it means redoing the work on a rented machine. But the app
under test is driven against a REAL Canvas account, so those artifacts carry the
operator's identity.

MEASURED 2026-08-21, on the set about to be committed: the Canvas login
`biso25ab` appeared **605 times in 138 files**, including `findings.jsonl` and
`report.html`. No token, no email and no JWT were present - the Panopto
`.ASPXAUTH` hits are the cookie NAME only, never a value - but a login id is
still the operator's identity at their university.

Idempotent: the placeholders do not match the patterns, so re-running is a
no-op. Run it before committing audit runs; `--check` fails without writing,
which is the form to use in a hook or in CI.

    python scripts/scrub_audit_pii.py            # redact in place
    python scripts/scrub_audit_pii.py --check    # report only, exit 1 if dirty
"""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: (label, pattern, replacement). Ordered: longer/more specific forms FIRST, or
#: a general rule redacts the prefix of a specific one and the specific rule
#: then never matches.
RULES: list[tuple[str, re.Pattern, str]] = [
    ("panopto unified login",
     re.compile(r"unified\\[A-Za-z0-9]+"), r"unified\\<CANVAS_USER>"),
    ("canvas login id",
     re.compile(r"\b[a-z]{4}\d{2}[a-z]{2}\b"), "<CANVAS_USER>"),
    ("email address",
     re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    ("canvas api token",
     re.compile(r"\b\d{4,5}~[A-Za-z0-9]{20,}"), "<CANVAS_TOKEN>"),
    ("bearer token",
     re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]{20,}"), r"\1<TOKEN>"),
    ("jwt",
     re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}[.A-Za-z0-9_-]*"),
     "<JWT>"),
]

#: Only text artifacts are scrubbed. Anything binary is excluded by .gitignore
#: rather than redacted - a partially-redacted binary is worse than no binary.
SUFFIXES = {".json", ".jsonl", ".txt", ".html", ".md", ".log", ".csv"}


def tracked_audit_files() -> list[Path]:
    """Every audit file git would commit, from git itself.

    Asking git rather than walking the tree is the point: the scrubber and the
    ignore rules can then never disagree about what is in scope.
    """
    out: list[Path] = []
    for args in (["git", "ls-files", "-z", "_audit_runs"],
                 ["git", "ls-files", "-z", "--others", "--exclude-standard",
                  "_audit_runs"]):
        # -z, and bytes rather than text=True. WITHOUT it git C-quotes any path
        # holding a non-ASCII byte - "...sm\303\245..." - Path() then names a
        # file that does not exist, is_file() answers False, and the file is
        # dropped in SILENCE. It fails in the worst available direction: the
        # scrubber reports CLEAN for a file it never opened. Every Danish course
        # name in this operator's runs hits it (46 files measured 2026-08-21).
        r = subprocess.run(args, cwd=REPO, capture_output=True)
        for raw in r.stdout.split(b"\0"):
            if not raw:
                continue
            p = REPO / raw.decode("utf-8")
            if p.suffix.lower() in SUFFIXES and p.is_file():
                out.append(p)
    return sorted(set(out))


def scrub_text(text: str) -> tuple[str, dict]:
    counts: dict = {}
    for label, rx, repl in RULES:
        text, n = rx.subn(repl, text)
        if n:
            counts[label] = counts.get(label, 0) + n
    return text, counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report without writing; exit 1 if anything would change")
    args = ap.parse_args()

    files = tracked_audit_files()
    total: dict = {}
    dirty: list[Path] = []
    for p in files:
        try:
            original = io.open(p, encoding="utf-8", newline="").read()
        except Exception:
            continue
        cleaned, counts = scrub_text(original)
        if not counts:
            continue
        dirty.append(p)
        for k, v in counts.items():
            total[k] = total.get(k, 0) + v
        if not args.check:
            io.open(p, "w", encoding="utf-8", newline="").write(cleaned)

    print(f"scanned {len(files)} audit text file(s)")
    if not total:
        print("CLEAN - nothing to redact")
        return 0
    verb = "would redact" if args.check else "redacted"
    for k, v in sorted(total.items(), key=lambda kv: -kv[1]):
        print(f"  {verb} {v:6d}x  {k}")
    print(f"  across {len(dirty)} file(s)")
    return 1 if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
