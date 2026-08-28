"""Set every `<lastmod>` in docs/sitemap.xml from the page's last commit date.

WHY THIS EXISTS. `docs/sitemap.xml` is hand-maintained and has no generator, so
its `lastmod` drifts silently every time a page is edited without somebody
remembering to touch the sitemap too. Measured 2026-08-29: commit `ef2eb1ae`
changed **19** pages under `docs/` and left all 22 `lastmod` values reading
`2026-08-27`.

That is not cosmetic. `lastmod` is the signal a search engine uses to decide
whether a URL is worth re-fetching, and `marketing/SEO_FINDINGS_2026-08-27.md`
measures crawl budget as this site's binding constraint: two articles Google has
discovered have never been fetched at all. Telling Google that nothing changed
is throwing away the one legitimate way to ask for a re-crawl.

`scripts/ping_indexnow.py` is NOT affected, because it derives its changed set
from `git diff` rather than from the sitemap. So before this script existed the
two engines were being told different things, and only Bing was being told the
truth.

Run it after editing anything under `docs/`, and commit the result in the same
commit as the page change:

    python scripts/sync_sitemap_lastmod.py            # report only
    python scripts/sync_sitemap_lastmod.py --write    # rewrite in place
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SITEMAP = DOCS / "sitemap.xml"
BASE = "https://canvasdownloader.app/"


def commit_date(path: pathlib.Path) -> str | None:
    """Last commit date for one file, as YYYY-MM-DD, or None if unknown.

    Returns None rather than raising on a shallow checkout: GitHub Actions
    clones with `fetch-depth: 1` by default, where `git log` for a path is
    legitimately empty. A guard that cannot see history must say so instead of
    reporting every page as stale.
    """
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", str(path)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    date = out.stdout.strip()
    return date or None


def local_path(loc: str) -> pathlib.Path:
    """Map a sitemap <loc> back to the file that serves it."""
    rel = loc[len(BASE):] if loc.startswith(BASE) else loc
    rel = rel.split("?", 1)[0].split("#", 1)[0]
    return DOCS / (rel if rel else "index.html")


def entries(xml: str) -> list[tuple[str, str | None]]:
    out = []
    for block in re.findall(r"(?s)<url>.*?</url>", xml):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block)
        if not loc:
            continue
        lm = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block)
        out.append((loc.group(1), lm.group(1) if lm else None))
    return out


def stale() -> tuple[list[tuple[str, str | None, str]], list[str]]:
    """(url, sitemap_lastmod, real_date) for every drifted entry, plus misses."""
    xml = SITEMAP.read_text(encoding="utf-8")
    drift, missing = [], []
    for loc, lm in entries(xml):
        path = local_path(loc)
        if not path.exists():
            missing.append(loc)
            continue
        real = commit_date(path)
        if real is None:
            continue                      # no history available; see docstring
        if lm != real:
            drift.append((loc, lm, real))
    return drift, missing


def rewrite() -> int:
    xml = SITEMAP.read_text(encoding="utf-8")
    changed = 0

    def fix(block: str) -> str:
        nonlocal changed
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block)
        if not loc:
            return block
        path = local_path(loc.group(1))
        real = commit_date(path) if path.exists() else None
        if real is None:
            return block
        if re.search(r"<lastmod>", block):
            new = re.sub(r"(<lastmod>)\s*.*?\s*(</lastmod>)",
                         r"\g<1>%s\g<2>" % real, block, count=1)
        else:
            new = block.replace("</loc>", "</loc>\n    <lastmod>%s</lastmod>" % real, 1)
        if new != block:
            changed += 1
        return new

    out = re.sub(r"(?s)<url>.*?</url>", lambda m: fix(m.group(0)), xml)
    if changed:
        SITEMAP.write_text(out, encoding="utf-8", newline="\n")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="rewrite docs/sitemap.xml in place")
    args = ap.parse_args()

    drift, missing = stale()
    for loc in missing:
        print("MISSING FILE  %s" % loc)
    if not drift:
        print("sitemap lastmod is in sync with git (%d URLs)"
              % len(entries(SITEMAP.read_text(encoding='utf-8'))))
        return 1 if missing else 0

    print("%d entr%s drifted:" % (len(drift), "y" if len(drift) == 1 else "ies"))
    for loc, lm, real in drift:
        print("  %-62s %s -> %s" % (loc.replace(BASE, "/"), lm or "(none)", real))
    if args.write:
        n = rewrite()
        print("\nrewrote %d entr%s in %s" % (n, "y" if n == 1 else "ies", SITEMAP.name))
        return 1 if missing else 0
    print("\nrun again with --write to fix")
    return 1


if __name__ == "__main__":
    sys.exit(main())
