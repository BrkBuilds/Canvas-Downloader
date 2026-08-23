"""Every internal link on the website must resolve to a file that exists.

Found 2026-08-20: ``docs/404.html`` still pointed at the GitHub Pages PROJECT
paths the site used before commit ``8a277be`` moved it to canvasdownloader.app -
``/Canvas-Downloader/releases.html`` and friends. Verified against the live
host: all nine returned **404**, including the page's own ``fonts.css`` and
favicon. So the one page whose entire job is to rescue a visitor who has
already hit a dead URL offered them four more dead URLs and rendered without
its font.

It survived the domain migration because the 404 page is the one page nobody
visits on purpose. Nothing links to it, so a click-through never reveals it, and
it is (correctly) excluded from the sitemap.

The rule this pins is deliberately broader than that one bug: any ``href`` or
``src`` pointing inside the site must name a file that exists in ``docs/``.

Note that ``404.html`` must use ROOT-relative paths (``/guide.html``). It is
served for a URL at any depth, so a bare ``guide.html`` would resolve against
whatever bogus directory the visitor typed. Every other page is flat and uses
plain relative paths, which is right for them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parent.parent / "docs"

# href="..." / src="..." that stay inside the site: not absolute URLs, not
# mailto/tel, not a bare fragment.
_LINK = re.compile(r'(?:href|src)="(?!https?:|mailto:|tel:|data:|#)([^"]+)"')

# An HTML COMMENT is not markup, and `docs/releases.html` carries one that says
# `THESE MUST STAY <a href="..."> ELEMENTS` - documenting the dead-button bug
# where a <button> received a scripted .href and both downloads were silently
# dead. Scanned raw, that explanatory `...` reads as a link to a file named
# `...` and the page fails as broken while every real link resolves.
#
# Same rule, same reason, as `scripts/verify_architecture.py` Rules 6 and 8,
# which blank comments before scanning so that documenting a hazard can never
# trip the check that polices it.
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _markup(html: str) -> str:
    """The page with its comments blanked, so only real markup is scanned."""
    return _COMMENT.sub("", html)


def _pages() -> list[Path]:
    pages = sorted(DOCS.glob("*.html"))
    assert pages, f"no pages found under {DOCS}"
    return pages


def _target(raw: str) -> Path:
    """Resolve one link to the file it names, dropping any #fragment or ?query."""
    path = raw.split("#", 1)[0].split("?", 1)[0]
    if not path:                       # a pure fragment or query
        return DOCS
    if path.startswith("/"):
        path = path[1:]
    if path in ("", "./"):
        path = "index.html"
    return DOCS / path


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_every_internal_link_resolves(page: Path):
    html = _markup(page.read_text(encoding="utf-8"))
    broken = []
    for raw in sorted(set(_LINK.findall(html))):
        target = _target(raw)
        if not target.exists():
            broken.append(f"{raw} -> {target.relative_to(DOCS.parent)}")
    assert not broken, (
        f"{page.name} links to files that do not exist: " + "; ".join(broken))


def test_no_page_still_uses_the_old_project_pages_prefix():
    """The site moved off username.github.io/Canvas-Downloader/ in 8a277be."""
    # Anchored on the ATTRIBUTE, because the same substring appears inside every
    # legitimate https://github.com/BrkBuilds/Canvas-Downloader/... link on the
    # site. Only a SITE-relative path starting with it is the bug.
    stale = re.compile(r'(?:href|src)="/Canvas-Downloader/')
    offenders = [p.name for p in _pages()
                 if stale.search(p.read_text(encoding="utf-8"))]
    assert not offenders, (
        "these pages still use the pre-custom-domain path prefix, which 404s on "
        f"canvasdownloader.app: {offenders}")


def test_the_404_page_uses_root_relative_paths():
    """A 404 is served at any depth, so relative paths there are a trap."""
    html = (DOCS / "404.html").read_text(encoding="utf-8")
    relative = [raw for raw in set(_LINK.findall(html)) if not raw.startswith("/")]
    assert not relative, (
        "404.html must use root-relative paths - it is served for a URL at any "
        f"depth, so these would resolve against the wrong directory: {sorted(relative)}")


def test_every_sitemap_url_exists_and_is_indexable():
    """A sitemap that lists a missing or noindex URL trains crawlers to distrust it."""
    import xml.etree.ElementTree as ET

    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring((DOCS / "sitemap.xml").read_text(encoding="utf-8"))
    urls = [u.find("s:loc", ns).text for u in root.findall("s:url", ns)]
    assert urls, "sitemap.xml lists no URLs"

    for url in urls:
        rel = url.replace("https://canvasdownloader.app/", "") or "index.html"
        page = DOCS / rel
        assert page.exists(), f"sitemap lists {url} but {rel} does not exist"
        html = page.read_text(encoding="utf-8")
        assert "noindex" not in html, (
            f"sitemap lists {url}, but that page carries a noindex robots meta. "
            f"Asking a crawler to index a page that forbids indexing is a "
            f"contradiction; drop it from the sitemap instead.")


def test_pages_excluded_from_the_sitemap_are_the_ones_that_should_be():
    """The two 'your download has started' pages and 404 are not content."""
    import xml.etree.ElementTree as ET

    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring((DOCS / "sitemap.xml").read_text(encoding="utf-8"))
    listed = {u.find("s:loc", ns).text.replace("https://canvasdownloader.app/", "")
              or "index.html" for u in root.findall("s:url", ns)}
    on_disk = {p.name for p in _pages()}
    missing = on_disk - listed - {"404.html", "thanks-win.html", "thanks-mac.html"}
    assert not missing, (
        f"these pages exist but are not in sitemap.xml: {sorted(missing)}. Add "
        f"them, or give them a noindex meta if they are not content.")

def test_every_same_origin_url_in_structured_data_resolves():
    """Schema that points at a missing file rots silently.

    Nothing renders a ``thumbnailUrl`` or a ``contentUrl``, so a broken one
    produces no visible symptom and no console error. It is only ever seen by a
    crawler, which is the one audience that cannot tell you it is broken.

    Added when VideoObject nodes were introduced for the four demo videos, whose
    poster images are generated from the videos and are therefore exactly the
    kind of asset that goes missing in a later cleanup.
    """
    import json

    broken = []
    for page in _pages():
        html = page.read_text(encoding="utf-8")
        for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                                html, re.S):
            for url in re.findall(r'"(https://canvasdownloader\.app/[^"]+)"',
                                  json.dumps(json.loads(block))):
                rel = url.replace("https://canvasdownloader.app/", "")
                # A bare page url or an #id reference names no file.
                if not rel or rel.startswith("#") or "#" in rel:
                    continue
                if not (DOCS / rel).exists():
                    broken.append(f"{page.name}: {url}")
    assert not broken, (
        "structured data points at files that do not exist: " + "; ".join(broken))



def test_every_videoobject_uploaddate_carries_a_timezone():
    """A date-only ``uploadDate`` is INVALID to Google, and it says so twice.

    Search Console reported both "Datetime property 'uploadDate' is missing a
    timezone" and "Invalid datetime value for 'uploadDate'" against all four
    VideoObject nodes on 2026-08-22. The value was a bare ``2026-08-14``:
    schema.org accepts a plain Date, but Google's VideoObject documentation
    requires an ISO 8601 datetime and treats a date-only value as neither.

    Both warnings are non-critical TODAY - the items stay valid and eligible -
    and Google's own notice says non-critical issues can be reclassified as
    critical later, at which point the video rich result goes away with no
    change on our side. Cheap insurance, not a live bug.

    Guarded rather than merely fixed because the value is INVISIBLE: no page
    renders ``uploadDate``, nothing else in the site's tests parsed it, and its
    only audience is a crawler - which reports the problem weeks later, by
    email, in whatever language the Search Console account is set to.

    **Deliberately scoped to ``uploadDate`` and not to every schema date.** The
    site also carries bare ``datePublished`` / ``dateModified`` on Article
    nodes across five pages, and those are FINE: Google's article guidance
    recommends a timezone but accepts a date, and Search Console has never
    flagged one. Widening this guard would force eleven edits to satisfy a
    requirement that does not exist, and a test stricter than the spec it
    guards teaches the next person to distrust it.
    """
    import json

    # A datetime with an offset: 2026-08-14T00:00:00+00:00, or ...Z.
    stamped = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$")

    naked, seen = [], 0
    for page in _pages():
        html = page.read_text(encoding="utf-8")
        for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                                html, re.S):
            def walk(node):
                nonlocal seen
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key == "uploadDate" and isinstance(value, str):
                            seen += 1
                            if not stamped.match(value):
                                naked.append(f"{page.name}: {value!r}")
                        walk(value)
                elif isinstance(node, list):
                    for item in node:
                        walk(item)

            walk(json.loads(block))

    # Without this the test passes vacuously the day the VideoObject nodes are
    # renamed or dropped, which is exactly when it would stop being checked.
    assert seen >= 4, f"expected the four demo VideoObject nodes, found {seen}"
    assert not naked, (
        "a VideoObject uploadDate must carry a timezone offset "
        "(YYYY-MM-DDThh:mm:ss+00:00); a bare date is invalid to Google: "
        + "; ".join(naked))
