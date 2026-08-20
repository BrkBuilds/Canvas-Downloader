"""A download control on the website must be an ANCHOR, never a button.

Found 2026-08-20 by measuring the live site. Commit ``31dd133`` ("website audit
and fixes to be 1-1 w app") converted three ``<a href="#">`` elements on
``docs/releases.html`` into ``<button type="button">``. That is the right move
for a JavaScript control, and the OS toggle got its ``addEventListener`` and
kept working. It is the WRONG move for a navigation: the release script still
ran ::

    el('win-exe').href = winAsset.browser_download_url;

and assigning ``.href`` to an ``HTMLButtonElement`` merely creates an expando
property. A button has no href behaviour and neither element had a click
handler, so **both "Download direct (.exe)" and "Download for macOS (.dmg)" did
nothing at all**, on the page reached from the nav and the footer of every other
page. Proved in a real browser against the real GitHub payload: clicking either
produced no navigation and no download, while the *older* releases below them -
built by ``makeAsset()`` as genuine ``<a>`` elements - downloaded fine. So the
newest build was the only one a visitor could not get.

It is invisible in review because the markup looks deliberate (the buttons even
carry a careful ``background:none; border:none; font:inherit`` reset to keep the
old look) and the page has no error state for it. Nothing in the suite covered
the website at all.

Two properties are asserted, because the defect needs both to come back:

1. **Every element that a script assigns ``.href`` to must be an ``<a>``.**
   This is the general rule and it catches the next occurrence anywhere on the
   site, not just the two ids that were broken.
2. **The primary download controls must carry a static ``href`` in the HTML.**
   The script overwrites it when GitHub answers, but a crawler that runs no
   JavaScript, and a visitor whose network blocks ``api.github.com``, must still
   get a working download rather than a spinner.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parent.parent / "docs"

_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _markup(page) -> str:
    """Page source with HTML COMMENTS removed.

    ``releases.html`` carries a maintenance block that quotes the very elements
    these tests look for (deliberately - it tells the next release author which
    tags must stay anchors). Matching against the raw file finds the quoted copy
    first and reports a fault that is not there. A comment is not markup.
    """
    return _COMMENT.sub("", page.read_text(encoding="utf-8"))

# `el('win-exe').href = ...`, `document.getElementById('x').href = ...`
_HREF_ASSIGN = re.compile(
    r"""(?:el|document\.getElementById)\(\s*['"]([A-Za-z0-9_-]+)['"]\s*\)\s*\.href\s*=""")


def _pages() -> list[Path]:
    pages = sorted(DOCS.glob("*.html"))
    assert pages, f"no pages found under {DOCS}"
    return pages


def _tag_of(html: str, element_id: str) -> str | None:
    """The tag name of the element carrying ``id="element_id"``, or None.

    Matches the id wherever it sits in the attribute list, because these
    elements routinely carry class/style/type before or after it.
    """
    m = re.search(r"<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*\bid=[\"']" + re.escape(element_id) + r"[\"']",
                  html)
    return m.group(1).lower() if m else None


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_every_scripted_href_assignment_targets_an_anchor(page: Path):
    html = _markup(page)
    offenders = []
    for element_id in set(_HREF_ASSIGN.findall(html)):
        tag = _tag_of(html, element_id)
        if tag is None:          # built by script, not present in the markup
            continue
        if tag != "a":
            offenders.append(f"#{element_id} is <{tag}>")
    assert not offenders, (
        f"{page.name}: a script assigns .href to an element that is not an anchor: "
        + ", ".join(sorted(offenders))
        + ". Setting .href on anything but <a> writes a dead property, so the "
          "control silently does nothing. Style the anchor instead of changing "
          "the tag."
    )


def test_the_release_downloads_work_without_javascript():
    """The two primary installers must be reachable from the static markup."""
    html = _markup(DOCS / "releases.html")

    for element_id, suffix in (("win-exe", ".exe"), ("mac-dmg", ".dmg")):
        m = re.search(r"<a\b[^>]*\bid=[\"']" + element_id + r"[\"'][^>]*>", html)
        assert m, (f"#{element_id} must exist as an <a> in releases.html - it is the "
                   f"page's primary {suffix} download")
        href = re.search(r"href=[\"']([^\"']+)[\"']", m.group(0))
        assert href, f"#{element_id} has no static href, so it is dead without JavaScript"
        url = href.group(1)
        assert url.lower().endswith(suffix), (
            f"#{element_id} points at {url!r}, which is not a {suffix} installer")
        assert url.startswith("https://github.com/BrkBuilds/Canvas-Downloader/releases/download/"), (
            f"#{element_id} must point at a GitHub release asset, got {url!r}")


def test_the_releases_page_shows_a_version_without_javascript():
    """A crawler used to see only "Loading the latest release...". Never again."""
    html = _markup(DOCS / "releases.html")
    for element_id in ("win-ver", "mac-ver"):
        m = re.search(r"<span\b[^>]*\bid=[\"']" + element_id + r"[\"'][^>]*>(.*?)</span>",
                      html, re.S)
        assert m, f"#{element_id} version pill is missing from releases.html"
        assert re.fullmatch(r"v\d+\.\d+\.\d+", m.group(1).strip()), (
            f"#{element_id} must carry the shipped version as static text "
            f"(got {m.group(1).strip()!r})")
