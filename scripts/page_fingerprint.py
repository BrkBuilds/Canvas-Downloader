"""Decide whether a page under `docs/` changed in a way a search engine cares about.

WHY THIS EXISTS. Every page under `docs/` carries its own copy of the shared
stylesheet - the twelve article pages hold a byte-identical 18.9 KB block, 462 KB
of duplicated CSS across the site - so any cosmetic sweep rewrites every file.
Measured 2026-09-01 across the five most recent website commits: **83 page writes,
76 of them (92%) with identical visible text.** Every one of those 76 moved
`<lastmod>` in the sitemap and put the URL into an IndexNow submission.

That matters because crawl budget is this site's measured constraint. Search
Console for 16-31 August: 193 crawl requests total, **82.38% of them "refresh" of
URLs Google already has against 17.62% "discovery"**, while seven pages had never
been fetched even once. Telling Google that all 24 URLs changed, every other day,
is the signal it uses to decide a site's `lastmod` is not worth trusting.

`ping_indexnow.py`'s own header already states the rule it was breaking:
*"re-announcing an unchanged set on every push is what receiving engines treat as
noise."* It derived its changed set from `git diff`, which cannot tell a CSS sweep
from a rewrite.

WHAT COUNTS AS A CHANGE. The fingerprint is deliberately conservative: it says
"unchanged" only when nothing a search engine reads has moved. It covers the
title, the meta description, the canonical, every JSON-LD block, every `href` and
`src` in document order, and the visible body text. It ignores `<style>`, ordinary
`<script>`, HTML comments, and pure tag or attribute churn - which is exactly the
accessibility, heading-level and stylesheet work that produced the 76.

    python scripts/page_fingerprint.py docs/guide.html            # print it
    python scripts/page_fingerprint.py --changed HEAD~1 docs/     # what really moved

This module is the ONE implementation. `sync_sitemap_lastmod.py` and
`ping_indexnow.py` both import it; do not write a second copy, because a second
copy is how a fix lands on half the site (see CLAUDE.md, "Write a rule once").
"""
from __future__ import annotations

import argparse
import hashlib
import html
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

_STYLE = re.compile(r"<style\b[^>]*>.*?</style>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_LDJSON = re.compile(r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                     re.S | re.I)
_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.S | re.I)
_META_DESC = re.compile(
    r'<meta\b[^>]*\bname=["\']description["\'][^>]*\bcontent=["\'](.*?)["\']', re.S | re.I)
_CANONICAL = re.compile(
    r'<link\b[^>]*\brel=["\']canonical["\'][^>]*\bhref=["\'](.*?)["\']', re.S | re.I)
# ANCHORS ONLY, and this distinction was measured rather than assumed. A first
# version captured every `href` and `src`, which reported commit `50fc5923` as 27
# real content changes; the whole diff was `icon.png` -> `assets/icon-128.webp`,
# the apple-touch-icon swap from the performance pass. An asset path is plumbing:
# swapping an icon or a poster gives a search engine nothing to re-read. An `<a>`
# is what a crawler follows and what a reader clicks, so that one is content.
# Adding an image without changing a word does not happen here anyway - it moves
# `text`, and for the six homepage videos it moves `ldjson` too.
_URLS = re.compile(r'<a\b[^>]*?\bhref=["\']([^"\']+)["\']', re.I | re.S)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fingerprint_parts(markup: str) -> dict[str, str]:
    """The search-relevant content of one page, as named parts.

    Returned as parts rather than one blob so a caller can say WHICH half moved,
    which is what makes a surprising result debuggable instead of merely true.
    """
    title = _TITLE.search(markup)
    desc = _META_DESC.search(markup)
    canon = _CANONICAL.search(markup)
    ldjson = " ".join(_norm(b) for b in _LDJSON.findall(markup))

    body = _STYLE.sub(" ", markup)
    body = _SCRIPT.sub(" ", body)          # ld+json already captured above
    body = _COMMENT.sub(" ", body)
    urls = " ".join(_URLS.findall(body))   # document order is part of the value
    text = _norm(_TAG.sub(" ", body))

    return {
        "title": _norm(title.group(1)) if title else "",
        "description": _norm(desc.group(1)) if desc else "",
        "canonical": _norm(canon.group(1)) if canon else "",
        "ldjson": ldjson,
        "urls": urls,
        "text": text,
    }


def fingerprint(markup: str) -> str:
    parts = fingerprint_parts(markup)
    joined = "\n\x1f".join(f"{k}={parts[k]}" for k in sorted(parts))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def changed_parts(before: str, after: str) -> list[str]:
    """Names of the fingerprint parts that differ. Empty means no real change."""
    a, b = fingerprint_parts(before), fingerprint_parts(after)
    return [k for k in sorted(a) if a[k] != b[k]]


def _git(args: list[str]) -> str:
    """Run git and decode as UTF-8 explicitly.

    Windows defaults to CP1252 and these pages are full of Danish characters and
    emoji, so `text=True` here decodes some pages wrongly and silently skips them.
    That exact mistake produced an 8-file census that only compared 5 files.
    """
    out = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=60)
    return out.stdout.decode("utf-8", "replace")


def _rel(path: str | pathlib.Path) -> str:
    """Repo-relative POSIX path, whatever form the caller passed.

    `git show <rev>:<path>` accepts ONLY a repo-relative path with forward
    slashes. Handed an absolute Windows path it fails silently with a non-zero
    exit, which made `blob_at` return None for every revision and
    `content_commit_date` fall through to the OLDEST commit for the file. The
    homepage came back as 2026-05-01 while its content had changed on 08-31, and
    every date in the sitemap looked plausible while being wrong. Normalise here,
    once, so no caller has to know.
    """
    p = pathlib.Path(path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(ROOT)
        except ValueError:
            return pathlib.Path(path).as_posix()
    return p.as_posix()


def blob_at(rev: str, path: str | pathlib.Path) -> str | None:
    """File contents at a revision, or None if it did not exist there."""
    out = subprocess.run(["git", "show", f"{rev}:{_rel(path)}"],
                         cwd=ROOT, capture_output=True, timeout=60)
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", "replace")


def content_changed(path: str | pathlib.Path, rev_a: str, rev_b: str = "HEAD") -> bool:
    """Did this page's search-relevant content change between two revisions?

    A file that is new in `rev_b`, or removed, counts as changed: there is no
    earlier content to compare against, and announcing a genuinely new URL is the
    whole point of the machinery this feeds.
    """
    before, after = blob_at(rev_a, path), blob_at(rev_b, path)
    if before is None or after is None:
        return True
    return bool(changed_parts(before, after))


def content_commit_date(path: str | pathlib.Path) -> str | None:
    """Date of the most recent commit that changed this page's CONTENT.

    Walks back through the file's own history and returns the first commit whose
    fingerprint differs from its parent's. Returns None when history is
    unavailable - a shallow CI checkout has no `git log` for a path, and a guard
    that cannot see history must say so rather than report every page as stale.
    """
    rel = _rel(path)
    log = _git(["git", "log", "--format=%H %cs", "--", rel]).split("\n")
    revs = [ln.split(" ", 1) for ln in log if ln.strip()]
    if not revs:
        return None
    for sha, date in revs:
        parent_ok = subprocess.run(["git", "rev-parse", "--verify", f"{sha}~1"],
                                   cwd=ROOT, capture_output=True, timeout=30).returncode == 0
        after = blob_at(sha, rel)
        if after is None:
            continue
        before = blob_at(f"{sha}~1", rel) if parent_ok else None
        if before is None or changed_parts(before, after):
            return date.strip()
    # Every commit touching it was cosmetic: fall back to the oldest one, which is
    # when the content it still carries was written.
    return revs[-1][1].strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", help="page paths, or a directory with --changed")
    ap.add_argument("--changed", metavar="REV",
                    help="list pages whose CONTENT changed between REV and HEAD")
    args = ap.parse_args(argv)

    if args.changed:
        files: list[str] = []
        for p in args.paths:
            files += [f for f in _git(["git", "diff", "--name-only", args.changed,
                                       "HEAD", "--", p]).split("\n")
                      if f.strip().endswith(".html")]
        real = [f for f in files if content_changed(f, args.changed)]
        print(f"{len(files)} page(s) written, {len(real)} with real content changes")
        for f in real:
            print("  " + f)
        cosmetic = sorted(set(files) - set(real))
        for f in cosmetic:
            print("  (cosmetic only) " + f)
        return 0

    for p in args.paths:
        path = pathlib.Path(p)
        if not path.exists():
            print(f"MISSING  {p}")
            continue
        parts = fingerprint_parts(path.read_text(encoding="utf-8"))
        print(f"{fingerprint(path.read_text(encoding='utf-8'))[:16]}  {p}")
        print(f"    title       {parts['title'][:70]}")
        print(f"    text words  {len(parts['text'].split())}")
        print(f"    urls        {len(parts['urls'].split())}")
        print(f"    last commit changing content: {content_commit_date(p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
