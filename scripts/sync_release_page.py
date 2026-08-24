"""Rewrite `docs/releases.html` and the sitemap from the ACTUAL GitHub releases.

`docs/releases.html` carries a maintenance block headed *"TO PUBLISH A NEW
VERSION, EDIT EXACTLY THESE SIX THINGS"*. Six hand edits plus the sitemap, on
release day, is seven chances to be wrong - and `marketing/FINDINGS.md` records
that class going wrong repeatedly: a homepage advertising a version nobody could
download, two download buttons that silently did nothing, an installer carrying a
third spelling of the repo URL, and release notes naming a Windows asset that
was not the one attached.

Every one of those facts is knowable from the release itself, so none of them
should be typed. This derives all of them:

* the two version pills                     <- the newest non-prerelease tag
* the two download hrefs                    <- the real asset `browser_download_url`
* the two "Version X · N MB · Released D"   <- the real asset `size`, the real date
* the JSON-LD block                         <- the same four facts
* the "Previous versions" static baseline   <- every older release with an asset
* `docs/sitemap.xml`'s `lastmod` for this page

THE ASSET NAMES ARE READ, NEVER CONSTRUCTED, and that is the point rather than a
detail. The Windows build emits `Canvas_Downloader_Setup_<ver>.exe` while the
release carries `Canvas_Downloader_v<ver>_Windows.exe`; the macOS workflow emits
`_macOS.dmg` while v2.0.1's asset is `_MacOS.dmg`. A script that built those
names from a template would be wrong on both counts, which is exactly how the
v2.0.1 notes came to name a file that is not attached to them.

THE VERSION IS THE SHIPPED TAG, NEVER `version.py`, which is deliberately kept
ahead of every tag so the in-app update banner works
(`tests/test_version_leads_tags.py`). The website must advertise what a visitor
can actually download.

    python scripts/sync_release_page.py --check    # report drift, write nothing
    python scripts/sync_release_page.py            # rewrite in place

`--check` is the form for CI and for a pre-release sanity pass. Run it BEFORE
tagging too: today it should report "already in sync", and that is the positive
control - a script that cannot reproduce the page as it stands has no business
writing the next one.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "docs" / "releases.html"
SITEMAP = REPO / "docs" / "sitemap.xml"
SLUG = "BrkBuilds/Canvas-Downloader"
PAGE_URL = "https://canvasdownloader.app/releases.html"

WIN_RE = re.compile(r"\.exe$", re.I)
MAC_RE = re.compile(r"\.dmg$", re.I)


# ── the facts ────────────────────────────────────────────────────────────────

def fetch_releases() -> list[dict]:
    """Every published release, newest first, via `gh`.

    Uses the CLI rather than an unauthenticated HTTP call so it inherits the
    operator's token and is not subject to the 60/hour anonymous rate limit -
    the same limit that makes the page's own client-side fetch fall back to the
    static markup this script maintains.

    ``encoding="utf-8"`` is LOAD-BEARING, and its absence made this whole script
    unrunnable on Windows. ``text=True`` alone decodes with the LOCALE encoding,
    which is cp1252 there - and a release body containing any character whose
    UTF-8 encoding includes byte 0x90 (an emoji, a dash) is undecodable in
    cp1252. The failure is worse than a crash: the decode happens on
    ``subprocess``'s own reader THREAD, whose exception is swallowed, so
    ``run()`` returns ``returncode == 0`` with ``stdout is None`` and the
    returncode guard above sails past it. Measured 2026-08-24: every one of the
    six guards in ``tests/test_website_advertises_shipped_version.py`` errored
    at setup with ``json.loads(None)`` -> ``TypeError``, and the Windows CI job
    had been red since. Same rule this project already states for ``open()``
    ("always specify encoding='utf-8' - Windows defaults to CP1252"); it had
    simply never been applied to ``subprocess``.

    The ``stdout is None`` guard stays anyway. It cannot fire now, and that is
    the point: a silent None is exactly the shape that produced a TypeError two
    frames away from its cause, and a decode set elsewhere must not be able to
    reintroduce it without saying so.
    """
    out = subprocess.run(
        ["gh", "api", f"repos/{SLUG}/releases", "--paginate"],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO,
    )
    if out.returncode != 0:
        raise SystemExit(f"gh api failed: {(out.stderr or '').strip()[:300]}")
    if out.stdout is None:
        raise SystemExit("gh api returned no output (its stdout could not be read)")
    rels = json.loads(out.stdout)
    return [r for r in rels if not r.get("draft")]


def newest_shipped_version() -> str | None:
    """THE definition of "shipped" for this project, or None if undeterminable.

    The newest release a visitor can actually download: not a draft, and **not a
    PRERELEASE**. Three things need this answer and they must not each decide it
    for themselves:

    * ``ui/update_banner.py`` asks GitHub for ``/releases/latest``, which
      excludes drafts and prereleases by definition;
    * this script, when it rewrites the download page;
    * ``tests/test_website_advertises_shipped_version.py``, which guards that
      the page states it.

    The test used to answer it with a bare ``git tag``, which knows nothing about
    prerelease status - so on 2026-08-22 a v2.0.2 PRERELEASE (macOS DMG only,
    published while the Windows installer was still being built) turned five
    guards red against a website that was correct, and would have "fixed" them by
    advertising a Windows download that does not exist. Same divergent-primitive
    shape as ``make_long_path`` having a second copy in ``core/sync_manager.py``.

    Returns None rather than raising when ``gh`` is missing or fails: "I cannot
    reach GitHub" is not evidence of a mistake, and the caller decides what to do
    about not knowing.
    """
    try:
        rels = fetch_releases()
    except (SystemExit, OSError, ValueError):
        # SystemExit: fetch_releases' own `gh api failed` exit, which is right
        # for the CLI and wrong for a caller that can carry on without an answer.
        # OSError: gh is not installed. ValueError: covers json.JSONDecodeError.
        return None
    for r in rels:
        if r.get("prerelease"):
            continue
        tag = (r.get("tag_name") or "").lstrip("vV").strip()
        if tag:
            return tag
    return None


def pick_asset(rel: dict, pattern: re.Pattern) -> dict | None:
    for a in rel.get("assets", []):
        if pattern.search(a.get("name", "")):
            return a
    return None


def newest_with(rels: list[dict], pattern: re.Pattern) -> tuple[dict, dict] | tuple[None, None]:
    """Newest NON-PRERELEASE release carrying a matching asset.

    Prereleases are skipped deliberately: v2.0.0 is flagged as one and carries a
    macOS asset, so including them would advertise it as current.
    """
    for r in rels:
        if r.get("prerelease"):
            continue
        a = pick_asset(r, pattern)
        if a:
            return r, a
    return None, None


def ver_of(rel: dict) -> str:
    return (rel.get("tag_name") or "").lstrip("v")


def date_of(rel: dict) -> _dt.date:
    return _dt.datetime.fromisoformat(
        rel["published_at"].replace("Z", "+00:00")).date()


def mb(asset: dict) -> str:
    """Size the way the page already states it: 1024-based, labelled "MB".

    NOT a bug being preserved - it is the page's existing convention and it is
    what GitHub's own release UI shows, so the two agree. Verified against the
    live page before this script was trusted to write it: 140,130,279 bytes ->
    133.6 and 151,503,877 -> 144.5, which is exactly what the page says. A
    decimal-MB reading would have "corrected" both to 140.1 and 151.5 and
    silently changed a number that was already right.
    """
    return f"{asset['size'] / 1024 / 1024:.1f}"


# ── the rewrites ─────────────────────────────────────────────────────────────

def _sub_once(text: str, pattern: str, repl, what: str, flags: int = 0) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        raise SystemExit(
            f"anchor for {what!r} matched {n} times - the page's markup moved. "
            "Fix this script rather than hand-editing the page, or the next "
            "release re-introduces the drift it exists to prevent.")
    return new


def rewrite_page(html: str, win, mac) -> str:
    win_rel, win_asset = win
    mac_rel, mac_asset = mac

    for who, rel, asset in (("win", win_rel, win_asset), ("mac", mac_rel, mac_asset)):
        v = ver_of(rel)
        # (A) version pill
        html = _sub_once(
            html, rf'(id="{who}-ver">)v[\d.]+(</span>)', rf'\g<1>v{v}\g<2>',
            f"{who} version pill")
        # (B) download href - MUST stay an <a>; a <button> has no href behaviour
        tag = "win-exe" if who == "win" else "mac-dmg"
        html = _sub_once(
            html, rf'(<a id="{tag}"[^>]*?href=")[^"]*(")',
            lambda m, u=asset["browser_download_url"]: m.group(1) + u + m.group(2),
            f"{who} download href")
        # (C) size + date line
        html = _sub_once(
            html,
            rf'(<p class="dl-meta" id="{who}-meta">)[^<]*(</p>)',
            lambda m, v=v, s=mb(asset), d=rel: (
                m.group(1)
                + f"Version {v} &middot; {s} MB &middot; Released "
                + f"{date_of(d).day} {date_of(d).strftime('%B %Y')}"
                + m.group(2)),
            f"{who} dl-meta")

    # (E) JSON-LD
    v = ver_of(win_rel)
    html = _sub_once(html, r'("softwareVersion": ")[\d.]+(")', rf'\g<1>{v}\g<2>',
                     "JSON-LD softwareVersion")
    html = _sub_once(html, r'("datePublished": ")[\d-]+(")',
                     rf'\g<1>{date_of(win_rel).isoformat()}\g<2>',
                     "JSON-LD datePublished")
    html = _sub_once(html, r'("fileSize": ")[^"]*(")',
                     rf'\g<1>{mb(win_asset)} MB\g<2>', "JSON-LD fileSize")
    html = _sub_once(
        html, r'("downloadUrl": \[\n)(?:[^\]]*?)(\n\s*\],)',
        lambda m: (m.group(1)
                   + f'          "{win_asset["browser_download_url"]}",\n'
                   + f'          "{mac_asset["browser_download_url"]}"'
                   + m.group(2)),
        "JSON-LD downloadUrl")
    html = _sub_once(html, r'("releaseNotes": ")[^"]*(")',
                     lambda m: m.group(1) + win_rel["html_url"] + m.group(2),
                     "JSON-LD releaseNotes")
    return html


_DL_SVG = ('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" '
           'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" '
           'stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>'
           '<polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'
           '</svg>')


def older_rows(rels, current_tags: set[str]) -> str:
    """(D) The crawlable no-JS baseline for "Previous versions".

    Regenerated wholesale rather than "move the row that was current", which is
    the step the maintenance block describes and the one most likely to be done
    by hand at 1 a.m. The page's own script replaces this list when GitHub
    answers, so it only has to be right for crawlers and for a rate-limited
    visitor - which is exactly who a hand-edited baseline lets down.
    """
    out = []
    for r in rels:
        if (r.get("tag_name") or "") in current_tags:
            continue
        w, m = pick_asset(r, WIN_RE), pick_asset(r, MAC_RE)
        if not (w or m):
            continue
        d = date_of(r)
        links = []
        if w:
            links.append(f'          <a class="rel-asset" href="{w["browser_download_url"]}">'
                         f'{_DL_SVG}Windows (.exe)</a>')
        if m:
            links.append(f'          <a class="rel-asset" href="{m["browser_download_url"]}">'
                         f'{_DL_SVG}macOS (.dmg)</a>')
        links.append(f'          <a class="rel-notes" href="{r["html_url"]}" '
                     f'target="_blank" rel="noopener">Notes &#8599;</a>')
        out.append(
            '      <div class="rel-row">\n'
            '        <div class="rel-meta">\n'
            f'          <div class="rel-ver">{r.get("name") or r["tag_name"]}</div>\n'
            f'          <div class="rel-date">{d.strftime("%b")} {d.day}, {d.year}</div>\n'
            '        </div>\n'
            '        <div class="rel-links">\n'
            + "\n".join(links) + "\n"
            '        </div>\n'
            '      </div>')
    return "\n".join(out)


def rewrite_older(html: str, block: str) -> str:
    return _sub_once(html, r'(<div id="older-list">\n)(?:.*?)(\n    </div>\n  </div>)',
                     lambda m: m.group(1) + block + m.group(2),
                     "older-list baseline", flags=re.S)


def rewrite_sitemap(xml: str, today: str) -> str:
    return _sub_once(
        xml,
        r'(<loc>https://canvasdownloader\.app/releases\.html</loc>\s*\n\s*<lastmod>)[\d-]+(</lastmod>)',
        rf'\g<1>{today}\g<2>', "sitemap lastmod for releases.html")


# ── entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit 1; write nothing")
    args = ap.parse_args()

    rels = fetch_releases()
    win = newest_with(rels, WIN_RE)
    mac = newest_with(rels, MAC_RE)
    if not win[0] or not mac[0]:
        raise SystemExit("no published release carries both a .exe and a .dmg")

    print(f"newest Windows : {win[0]['tag_name']}  {win[1]['name']}  {mb(win[1])} MB")
    print(f"newest macOS   : {mac[0]['tag_name']}  {mac[1]['name']}  {mb(mac[1])} MB")

    html = PAGE.read_text(encoding="utf-8")
    new = rewrite_page(html, win, mac)
    new = rewrite_older(new, older_rows(
        rels, {win[0]["tag_name"], mac[0]["tag_name"]}))

    xml = SITEMAP.read_text(encoding="utf-8")
    new_xml = xml
    if new != html:      # only touch lastmod when the page actually changed
        new_xml = rewrite_sitemap(xml, _dt.date.today().isoformat())

    changed = [n for n, a, b in (("docs/releases.html", html, new),
                                 ("docs/sitemap.xml", xml, new_xml)) if a != b]
    if not changed:
        print("\nalready in sync - nothing to write")
        return 0

    if args.check:
        print("\nDRIFT: " + ", ".join(changed))
        print("run without --check to rewrite, then run the suite")
        return 1

    PAGE.write_text(new, encoding="utf-8")
    SITEMAP.write_text(new_xml, encoding="utf-8")
    print("\nrewrote: " + ", ".join(changed))
    print("now run: python -m pytest tests/test_website_advertises_shipped_version.py "
          "tests/test_website_download_links.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
