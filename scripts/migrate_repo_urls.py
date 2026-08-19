"""Rewrite every hardcoded GitHub owner/repo reference after an org transfer or rename.

Ran once on 2026-08-19 for the move to the BrkBuilds organisation. Kept because a
repository can move again, and because it records exactly which files carry the
owner/repo pair.

    python scripts/migrate_repo_urls.py            # dry run, prints what would change
    python scripts/migrate_repo_urls.py --apply    # write the changes

RUN IT ONLY AFTER THE MOVE HAS HAPPENED ON GITHUB, never before. GitHub
301-redirects the old url to the new one, so a tree still holding old urls is
merely stale and every link keeps working. A tree holding new urls before the
move is broken, because the new path does not exist yet. That asymmetry is the
whole reason this is a separate script instead of an edit made up front.

Two substitutions, and the order matters:

1. ``<old owner>/<old repo>`` -> ``<new owner>/<new repo>``. Covers github.com
   links, api.github.com endpoints, and the shields.io badge paths, which carry
   the owner/repo pair with no github.com prefix in front of it.
2. Any REMAINING bare ``<old repo>`` -> ``<new repo>``. This is the clone
   directory name. It has to run second, or it would eat the repo half of rule 1
   first and leave the owner unchanged.

WHAT IS DELIBERATELY NOT TOUCHED
--------------------------------
``tests/audit/WEBSITE_LAUNCH_AUDIT.html`` is a DATED RECORD of what was audited
at the time of the domain migration. It keeps the old urls on purpose; rewriting
it would falsify the register.

**This file excludes ITSELF, and that is load-bearing.** The constants below are
string literals containing the very text being replaced, so without the
exclusion the script rewrites its own ``OLD_*`` values into the ``NEW_*`` ones
and can never run again: the two become identical and every later run is a
silent no-op. That is exactly what happened on the first real run. The damage
was confined to this file, because Python reads the constants at import time and
writing to the .py on disk does not change the values already in memory, so all
21 other files still received the correct substitution.

``birkls.github.io`` is not rewritten anywhere. It survives in exactly two
places and both are correct as they stand: the audit record above, and a
docstring in ``tests/test_legal_ack.py`` that cites the old host as history
while deriving the real one from ``legal.DISCLAIMER_URL``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Assembled from parts so this file cannot match its own search string. That is
# a second, cheaper guard than the self-exclusion below; the exclusion is what
# actually protects the file, this only stops a self-match if the exclusion is
# ever removed.
OLD_OWNER = "birkls"
OLD_REPO = "Canvas" + "_LMS_batch_file_" + "downloader"
NEW_OWNER = "BrkBuilds"
NEW_REPO = "Canvas-Downloader"

OLD_OWNER_REPO = f"{OLD_OWNER}/{OLD_REPO}"
NEW_OWNER_REPO = f"{NEW_OWNER}/{NEW_REPO}"

SELF = Path(__file__).resolve()
REPO_ROOT = SELF.parent.parent

# Records that must keep the old urls. Paths are repo-relative, posix style.
EXCLUDED = {
    "tests/audit/WEBSITE_LAUNCH_AUDIT.html",
    "scripts/migrate_repo_urls.py",
}

# Directories that never contain source we own.
SKIP_DIRS = {
    ".git", "__pycache__", "build", "dist", "_audit_runs", ".pytest_cache",
    "node_modules", ".playwright-mcp", "scratch", "panopto_models", "diagnostics",
}

SUFFIXES = {".py", ".md", ".html", ".yml", ".yaml", ".txt", ".sh", ".iss", ".spec", ".json", ".css", ".js"}


def candidate_files() -> list[Path]:
    out: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        if path.resolve() == SELF:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.relative_to(REPO_ROOT).as_posix() in EXCLUDED:
            continue
        out.append(path)
    return sorted(out)


def rewrite(text: str) -> tuple[str, int]:
    """Apply both substitutions. Returns the new text and the number of hits."""
    hits = text.count(OLD_OWNER_REPO)
    text = text.replace(OLD_OWNER_REPO, NEW_OWNER_REPO)
    # Order matters: only bare repo names survive to here.
    hits += text.count(OLD_REPO)
    text = text.replace(OLD_REPO, NEW_REPO)
    return text, hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the changes (default is a dry run)")
    args = ap.parse_args()

    if OLD_OWNER_REPO == NEW_OWNER_REPO:
        print("Old and new are identical - there is nothing this script could do.")
        return 2

    total_files = 0
    total_hits = 0

    for path in candidate_files():
        try:
            original = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if OLD_REPO not in original:
            continue

        updated, hits = rewrite(original)
        if updated == original:
            continue

        total_files += 1
        total_hits += hits
        print(f"  {hits:>3}  {path.relative_to(REPO_ROOT).as_posix()}")

        if args.apply:
            path.write_text(updated, encoding="utf-8", newline="")

    print()
    if total_files == 0:
        print("Nothing to change. Either the migration already ran, or the tree is clean.")
        return 0

    verb = "Rewrote" if args.apply else "Would rewrite"
    print(f"{verb} {total_hits} occurrence(s) across {total_files} file(s).")
    print(f"  {OLD_OWNER_REPO}  ->  {NEW_OWNER_REPO}")
    print(f"  {OLD_REPO}  ->  {NEW_REPO}")
    print()
    print(f"Kept unchanged on purpose: {', '.join(sorted(EXCLUDED))}")

    if not args.apply:
        print()
        print("Dry run. Re-run with --apply to write these changes.")
        print("Do this only AFTER the repository has been moved on GitHub.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
