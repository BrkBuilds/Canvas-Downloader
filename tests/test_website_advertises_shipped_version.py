"""The website must advertise the version a visitor can actually download.

``version.py`` is deliberately kept AHEAD of every shipped tag - see
``tests/test_version_leads_tags.py``, which exists because the update banner
compares the newest GitHub tag against the running build. So ``version.py`` is
the wrong source for anything user-facing on the website: on 2026-08-20 it said
``2.0.2`` while the newest release was ``v2.0.1``, and the homepage's
``SoftwareApplication`` JSON-LD dutifully advertised ``2.0.2`` - a build no user
could obtain, offered to search engines and to any assistant reading the markup.

The right source is the newest shipped TAG. This test pins every place the site
states a version to that one number, so the two can never drift again:

* the two version pills on ``releases.html``;
* the ``Version X.Y.Z`` line under each download button;
* the version inside each download URL (``/releases/download/vX.Y.Z/...``);
* ``softwareVersion`` in the JSON-LD of both ``releases.html`` and ``index.html``.

Like its sibling it SKIPS rather than fails when tags are not visible (a shallow
CI clone, or a source tree with no git), because "I cannot see the tags" is not
evidence of a mistake.

When you publish a release, ``docs/releases.html`` carries a maintenance block
listing exactly what to change; this test is what tells you if you missed one.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _markup(page) -> str:
    """Page source with HTML COMMENTS removed.

    ``releases.html`` carries a maintenance block that quotes the very elements
    these tests look for (deliberately - it tells the next release author which
    tags must stay anchors). Matching against the raw file finds the quoted copy
    first and reports a fault that is not there. A comment is not markup.
    """
    return _COMMENT.sub("", page.read_text(encoding="utf-8"))


def _version_tuple(s: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in s.strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


def _newest_tag() -> str | None:
    try:
        r = subprocess.run(["git", "tag"], cwd=REPO, capture_output=True,
                           text=True, timeout=30)
    except Exception:                                           # noqa: BLE001
        return None
    if r.returncode != 0:
        return None
    tags = [t for t in (r.stdout or "").split() if t.strip()]
    if not tags:
        return None
    return max(tags, key=_version_tuple).lstrip("vV")


@pytest.fixture(scope="module")
def shipped() -> str:
    tag = _newest_tag()
    if tag is None:
        pytest.skip("no git tags visible (shallow clone or no git) - "
                    "cannot judge what has shipped")
    return tag


def _json_ld(page: Path) -> list[dict]:
    html = _markup(page)
    nodes: list[dict] = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                            html, re.S):
        data = json.loads(block)
        nodes.extend(data.get("@graph", [data]))
    return nodes


def test_release_page_pills_state_the_shipped_version(shipped: str):
    html = _markup(DOCS / "releases.html")
    for element_id in ("win-ver", "mac-ver"):
        m = re.search(r"<span\b[^>]*\bid=[\"']" + element_id + r"[\"'][^>]*>(.*?)</span>",
                      html, re.S)
        assert m, f"#{element_id} is missing from releases.html"
        assert m.group(1).strip() == f"v{shipped}", (
            f"#{element_id} says {m.group(1).strip()!r} but the newest shipped tag "
            f"is v{shipped}")


def test_release_page_meta_lines_state_the_shipped_version(shipped: str):
    html = _markup(DOCS / "releases.html")
    stated = re.findall(r'class="dl-meta"[^>]*>Version\s+([0-9.]+)\s', html)
    assert len(stated) == 2, (
        f"expected one 'Version X.Y.Z' line per platform card, found {len(stated)}")
    for v in stated:
        assert v == shipped, f"a download card advertises {v} but v{shipped} is the newest tag"


def test_download_urls_point_at_the_shipped_release(shipped: str):
    html = _markup(DOCS / "releases.html")
    for element_id in ("win-exe", "mac-dmg"):
        m = re.search(r"<a\b[^>]*\bid=[\"']" + element_id + r"[\"'][^>]*href=[\"']([^\"']+)[\"']",
                      html)
        assert m, f"#{element_id} has no static href in releases.html"
        tag_in_url = re.search(r"/releases/download/v([0-9.]+)/", m.group(1))
        assert tag_in_url, f"#{element_id} href is not a release-asset URL: {m.group(1)!r}"
        assert tag_in_url.group(1) == shipped, (
            f"#{element_id} downloads v{tag_in_url.group(1)} but v{shipped} is the newest tag")


@pytest.mark.parametrize("page_name", ["index.html", "releases.html"])
def test_structured_data_states_the_shipped_version(shipped: str, page_name: str):
    versions = [n["softwareVersion"] for n in _json_ld(DOCS / page_name)
                if "softwareVersion" in n]
    assert versions, f"{page_name}: no softwareVersion in its JSON-LD"
    for v in versions:
        assert v == shipped, (
            f"{page_name}: JSON-LD advertises softwareVersion {v!r}, but the newest "
            f"shipped tag is v{shipped}. Do NOT take this number from version.py - "
            f"that is deliberately ahead of every tag.")


def test_the_site_never_advertises_the_in_development_version(shipped: str):
    """A guard on the specific mistake that was found, from the other direction."""
    from version import __version__

    if _version_tuple(__version__) <= _version_tuple(shipped):
        pytest.skip("version.py is not ahead of the newest tag right now, so there "
                    "is no in-development number that could leak")
    for page_name in ("index.html", "releases.html"):
        for node in _json_ld(DOCS / page_name):
            assert node.get("softwareVersion") != __version__, (
                f"{page_name} advertises {__version__}, which is version.py's "
                f"in-development number. Nobody can download it.")
