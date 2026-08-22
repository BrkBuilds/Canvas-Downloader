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
import sys
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
    """The newest version a visitor can actually DOWNLOAD.

    Deliberately NOT ``git tag``. A tag says nothing about whether its release
    is a prerelease, and on 2026-08-22 that difference turned every test in this
    file red against a website that was correct: v2.0.2 was tagged and published
    as a PRERELEASE carrying only the macOS DMG, while the Windows installer was
    still being built. Taking the raw newest tag would have "fixed" the failure
    by pointing the site's Windows download button at an asset that does not
    exist - the precise mistake this file was written to prevent.

    ``scripts/sync_release_page.py:newest_shipped_version`` is the single
    definition, shared with the tool that WRITES this page, and it matches what
    ``ui/update_banner.py`` sees (``/releases/latest`` excludes prereleases).
    Three consumers, one answer.

    Skips when it cannot be determined, which needs ``gh``. That is coherent
    rather than a hole: the only thing that changes these pages is
    ``sync_release_page.py``, which requires ``gh`` too - so the guard runs
    wherever the action it guards can be taken. The half that needs no network
    is ``test_the_advertised_version_is_internally_consistent_and_real`` below.
    """
    sys.path.insert(0, str(REPO))
    from scripts.sync_release_page import newest_shipped_version

    v = newest_shipped_version()
    if v is None:
        pytest.skip("cannot determine the newest NON-PRERELEASE release "
                    "(gh missing, unauthenticated, or offline) - a bare git tag "
                    "is not a substitute, see this fixture's docstring")
    return v


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


def test_the_advertised_version_is_internally_consistent_and_real():
    """The half that needs no network, so this file is never vacuous.

    Two properties, both locally decidable:

    * every place the site states a version states the SAME one. The five
      surfaces above are edited by one script; if they ever disagree, one of
      them was hand-edited and the page is lying to somebody regardless of
      which number is right.
    * that version is a real git tag. This is the original documented bug seen
      from the only angle that survives without GitHub: on 2026-08-20 the
      homepage advertised 2.0.2 - version.py's in-development number - when no
      such tag existed and nobody could download it.

    It deliberately does NOT judge whether that tag is the NEWEST shipped one;
    that needs prerelease status, which is what the ``shipped`` fixture is for.
    """
    html = _markup(DOCS / "releases.html")

    stated: set[str] = set()
    for element_id in ("win-ver", "mac-ver"):
        m = re.search(r"<span\b[^>]*\bid=[\"']" + element_id + r"[\"'][^>]*>(.*?)</span>",
                      html, re.S)
        assert m, f"#{element_id} is missing from releases.html"
        stated.add(m.group(1).strip().lstrip("vV"))
    stated.update(re.findall(r'class="dl-meta"[^>]*>Version\s+([0-9.]+)\s', html))
    # Scoped to the two CURRENT download buttons by id, never a blanket sweep
    # of the page: releases.html also carries a "Previous versions" baseline
    # full of older /releases/download/vX/ URLs, which are supposed to name
    # older versions. A first draft of this test swept those up and reported a
    # correct page as inconsistent.
    for element_id in ("win-exe", "mac-dmg"):
        m = re.search(r"<a\b[^>]*\bid=[\"']" + element_id + r"[\"'][^>]*href=[\"']([^\"']+)[\"']",
                      html)
        assert m, f"#{element_id} has no static href in releases.html"
        u = re.search(r"/releases/download/v([0-9.]+)/", m.group(1))
        assert u, f"#{element_id} href is not a release-asset URL: {m.group(1)!r}"
        stated.add(u.group(1))
    for page_name in ("index.html", "releases.html"):
        stated.update(n["softwareVersion"] for n in _json_ld(DOCS / page_name)
                      if "softwareVersion" in n)

    assert len(stated) == 1, (
        f"the site states more than one version at once: {sorted(stated)}. "
        f"These surfaces are all written by scripts/sync_release_page.py - a "
        f"disagreement means one was hand-edited.")

    advertised = stated.pop()
    tags = {t.lstrip("vV") for t in _tags()}
    if not tags:
        pytest.skip("no git tags visible - cannot check the version is real")
    assert advertised in tags, (
        f"the site advertises v{advertised}, which is not a tag in this repo. "
        f"Nobody can download it. Known tags: {sorted(tags)}")


def _tags() -> list[str]:
    try:
        r = subprocess.run(["git", "tag"], cwd=REPO, capture_output=True,
                           text=True, timeout=30)
    except Exception:                                           # noqa: BLE001
        return []
    if r.returncode != 0:
        return []
    return [t for t in (r.stdout or "").split() if t.strip()]
