"""The sitemap's `lastmod` must not be older than the page's last commit.

`docs/sitemap.xml` has no generator, so its dates drift every time somebody
edits a page and forgets the sitemap. Measured 2026-08-29: one commit changed 19
pages under `docs/` and left all 22 `lastmod` values a day stale. That matters
because `lastmod` is how a search engine decides whether to re-fetch, and
`marketing/SEO_FINDINGS_2026-08-27.md` measures crawl budget as this site's
binding constraint.

Fix a failure with `python scripts/sync_sitemap_lastmod.py --write`.

This is a test rather than a scanner because staleness is a FACT, not a
judgement about prose. The AI-tell scanner next door is deliberately not a test
for the opposite reason.
"""
import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sync_sitemap_lastmod as S  # noqa: E402


def test_sitemap_exists_and_parses():
    assert S.SITEMAP.exists(), "docs/sitemap.xml is missing"
    rows = S.entries(S.SITEMAP.read_text(encoding="utf-8"))
    assert rows, "no <url> entries parsed out of the sitemap"
    assert all(loc.startswith("https://") for loc, _ in rows)


def test_every_loc_has_a_file_behind_it():
    """A sitemap entry with no file is a 404 announced to two search engines."""
    _, missing = S.stale()
    assert not missing, "sitemap lists URLs with no file in docs/: %s" % missing


def test_lastmod_is_not_stale():
    xml = S.SITEMAP.read_text(encoding="utf-8")
    rows = S.entries(xml)

    checked = 0
    stale = []
    for loc, lm in rows:
        path = S.local_path(loc)
        if not path.exists():
            continue                      # covered by its own test above
        real = S.commit_date(path)
        if real is None:
            continue                      # shallow checkout, no history to read
        checked += 1
        if lm is None or lm < real:
            stale.append((loc.replace(S.BASE, "/"), lm, real))

    if checked == 0:
        pytest.skip("no git history available for docs/ (shallow checkout)")

    assert not stale, (
        "sitemap lastmod is older than the page's last commit for %d URL(s). "
        "Run: python scripts/sync_sitemap_lastmod.py --write\n%s"
        % (len(stale), "\n".join("  %s  %s -> %s" % r for r in stale)))


def test_the_check_can_actually_fail():
    """A guard that cannot say no is worth nothing.

    Drive the comparison the test relies on with a value known to be stale,
    rather than trusting that a green run means the logic works.
    """
    rows = S.entries(S.SITEMAP.read_text(encoding="utf-8"))
    loc = rows[0][0]
    real = S.commit_date(S.local_path(loc))
    if real is None:
        pytest.skip("no git history available")
    assert "1999-01-01" < real, "sanity: dates compare as strings"
