"""`scripts/sync_release_page.py`'s anchors must still resolve against the page.

The script rewrites `docs/releases.html` from the actual GitHub releases, which
removes the seven hand edits the page's own maintenance block asks for. That is
only worth having while its anchors still match: a regex that has stopped
matching turns release day into "the script errored, I'll just edit it by hand",
which is precisely the situation it exists to prevent - and the page's markup is
edited far more often than the script is.

This is the same decay `tests/test_mutation_anchors.py` catches for the mutation
harnesses: **an anchor that no longer resolves is not a failure you want to
discover at the moment you need the tool.** So it fails the SUITE, in the commit
that moves the markup.

It runs entirely offline against a synthetic release payload - no `gh`, no
network - so it is not a second copy of the script's own positive control (which
is `--check` reporting "already in sync" against the real API, and is a
different assertion: that the script agrees with reality).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "docs" / "releases.html"
SITEMAP = REPO / "docs" / "sitemap.xml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "sync_release_page_under_test", REPO / "scripts" / "sync_release_page.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


srp = _load()


def _release(tag, assets, *, prerelease=False, name=None):
    return {
        "tag_name": tag,
        "name": name or f"Canvas Downloader {tag}",
        "prerelease": prerelease,
        "draft": False,
        "published_at": "2026-09-01T10:00:00Z",
        "html_url": f"https://github.com/BrkBuilds/Canvas-Downloader/releases/tag/{tag}",
        "assets": [
            {"name": n, "size": s,
             "browser_download_url":
                 f"https://github.com/BrkBuilds/Canvas-Downloader/releases/download/{tag}/{n}"}
            for n, s in assets
        ],
    }


NEXT = _release("v2.0.2", [("Canvas_Downloader_v2.0.2_Windows.exe", 141_000_000),
                          ("Canvas_Downloader_v2.0.2_macOS.dmg", 152_000_000)])
WIN = (NEXT, NEXT["assets"][0])
MAC = (NEXT, NEXT["assets"][1])


# ── every anchor still resolves ──────────────────────────────────────────────

def test_every_page_anchor_still_resolves():
    """`_sub_once` raises SystemExit when a pattern matches 0 or 2+ times, so a
    clean run IS the assertion that all nine anchors are live."""
    srp.rewrite_page(PAGE.read_text(encoding="utf-8"), WIN, MAC)


def test_the_older_list_anchor_still_resolves():
    srp.rewrite_older(PAGE.read_text(encoding="utf-8"), "      <!-- rows -->")


def test_the_sitemap_anchor_still_resolves():
    srp.rewrite_sitemap(SITEMAP.read_text(encoding="utf-8"), "2026-09-01")


# ── and the rewrite actually says the new thing ──────────────────────────────

def test_the_rewrite_advertises_the_new_version_everywhere():
    out = srp.rewrite_page(PAGE.read_text(encoding="utf-8"), WIN, MAC)
    assert 'id="win-ver">v2.0.2<' in out
    assert 'id="mac-ver">v2.0.2<' in out
    assert '"softwareVersion": "2.0.2"' in out
    assert out.count("Canvas_Downloader_v2.0.2_Windows.exe") >= 2   # href + JSON-LD
    assert out.count("Canvas_Downloader_v2.0.2_macOS.dmg") >= 2


_COMMENT = re.compile(r"<!--.*?-->", re.S)


def test_no_trace_of_the_previous_version_survives_in_the_current_cards():
    """The failure mode is a PARTIAL update - a pill bumped and an href left
    behind, which is a live page offering the previous build under the new
    number. Assert the whole current-release region moved together.

    HTML comments are stripped first, the same way
    ``test_website_advertises_shipped_version.py`` does and for the same reason:
    the maintenance block deliberately quotes concrete version strings as
    examples (``Format is "v2.0.1"``, and the asset-naming trap), so scanning
    raw source reads documentation as a stale reference. Caught by this test's
    own first run, which is what the example is now warning the next person
    about.
    """
    out = srp.rewrite_page(PAGE.read_text(encoding="utf-8"), WIN, MAC)
    head = _COMMENT.sub(" ", out[:out.index('<div id="older-list">')])
    stale = re.findall(r"v?2\.0\.1", head)
    assert not stale, (
        f"{len(stale)} live reference(s) to the old version survive in the "
        "current cards - a partial update offers the previous build under the "
        "new number")


def test_the_asset_names_are_READ_not_CONSTRUCTED():
    """The whole point. The Windows build emits `Canvas_Downloader_Setup_<ver>.exe`
    and the release carries `Canvas_Downloader_v<ver>_Windows.exe`; the macOS
    workflow emits `_macOS.dmg` while v2.0.1's asset is `_MacOS.dmg`. A template
    would be wrong on both counts."""
    odd = _release("v9.9.9", [("some-other-name.exe", 1), ("WEIRDLY.Named.dmg", 2)])
    out = srp.rewrite_page(PAGE.read_text(encoding="utf-8"),
                           (odd, odd["assets"][0]), (odd, odd["assets"][1]))
    assert "some-other-name.exe" in out and "WEIRDLY.Named.dmg" in out


def test_sizes_use_the_pages_own_1024_based_convention():
    """Verified against the live page: 140,130,279 -> 133.6 and 151,503,877 ->
    144.5, which is exactly what it already says. A decimal-MB reading would
    silently 'correct' a number that was right."""
    assert srp.mb({"size": 140_130_279}) == "133.6"
    assert srp.mb({"size": 151_503_877}) == "144.5"


# ── the rules the page's own maintenance block states ────────────────────────

def test_the_download_targets_stay_ANCHORS_never_buttons():
    """`marketing/FINDINGS.md`: both download buttons on this page were dead for
    six days after three `<a href="#">` became `<button>`, because the script
    assigns `element.href` and a button has no href behaviour."""
    out = srp.rewrite_page(PAGE.read_text(encoding="utf-8"), WIN, MAC)
    for tag in ("win-exe", "mac-dmg"):
        assert re.search(rf'<a id="{tag}"', out), f"{tag} is no longer an anchor"


def test_a_prerelease_is_never_advertised_as_current():
    """v2.0.0 is flagged prerelease and carries a macOS asset, so a naive
    'newest release with a .dmg' would offer it as the current build."""
    rels = [_release("v2.0.0-rc", [("x.dmg", 1)], prerelease=True),
            _release("v1.9.0", [("y.dmg", 2)])]
    rel, asset = srp.newest_with(rels, srp.MAC_RE)
    assert rel["tag_name"] == "v1.9.0"


def test_a_draft_release_is_never_advertised(monkeypatch):
    """A draft is invisible to everyone but the maintainer, so advertising it is
    a download link to a 404 - and a draft is exactly what exists in the minutes
    between creating a release and publishing it, which is when someone is most
    likely to run this.

    The first version of this test asserted ``json.loads('[]') == []``, which is
    vacuous - it would have passed with the draft filter deleted. Drive the real
    ``fetch_releases`` against a stubbed ``gh`` instead.
    """
    payload = srp.json.dumps([
        _release("v9.9.9", [("draft.exe", 1)]) | {"draft": True},
        _release("v1.9.0", [("real.exe", 2)]),
    ])
    monkeypatch.setattr(
        srp.subprocess, "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": payload, "stderr": ""})())
    tags = [r["tag_name"] for r in srp.fetch_releases()]
    assert tags == ["v1.9.0"], tags


def test_a_failing_gh_call_STOPS_rather_than_writing_a_half_page(monkeypatch):
    """No network, a bad token or a rate limit must not produce an edit.

    Silently writing whatever it could parse is how a release page ends up
    advertising nothing, and the page's own client-side fetch already has this
    rule: 'if the API call fails, do nothing. Never replace working markup with
    an error state.'
    """
    monkeypatch.setattr(
        srp.subprocess, "run",
        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "",
                                       "stderr": "HTTP 403 rate limit"})())
    with pytest.raises(SystemExit) as e:
        srp.fetch_releases()
    assert "rate limit" in str(e.value)


def test_the_older_list_excludes_whatever_is_currently_featured():
    """Otherwise the current release appears twice - once in its card and once
    under 'Previous versions'."""
    older = _release("v1.0.0", [("old.exe", 3)])
    block = srp.older_rows([NEXT, older], {"v2.0.2"})
    assert "v2.0.2" not in block
    assert "old.exe" in block


def test_the_older_list_skips_a_release_with_no_installer():
    """A source-only or notes-only release has nothing to offer on this page."""
    empty = _release("v0.9.0", [])
    assert srp.older_rows([empty], set()).strip() == ""


# ── the page still tells a human where the rule lives ────────────────────────

def test_the_maintenance_block_points_at_the_script():
    """A page that still says 'edit exactly these six things' invites the hand
    edit this script exists to remove."""
    html = PAGE.read_text(encoding="utf-8")
    assert "sync_release_page.py" in html, (
        "releases.html's maintenance block does not mention the script, so the "
        "next release author will hand-edit it")
