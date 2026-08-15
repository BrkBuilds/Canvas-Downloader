"""What the WEBSITE says about logging in must still be true of the app.

The site is where a stuck user goes, and it is the one surface that cannot be
corrected by reading the code - it is served from `docs/` to a browser that
never sees this repo. Three of its login claims went stale without anyone
noticing, and each was invisible in review for the same reason: the sentence
stayed grammatical while the app moved underneath it.

  * mac-setup told people to log in "in the sidebar" - the login has been a
    full-page portal for a long time;
  * it also told them to tap the "?" beside the token field "for a step-by-step
    guide to generating one". That control is a tooltip explaining WHY a token
    is needed. It has never been a guide;
  * the institution count is quoted as a hard number on three pages, and
    nothing tied it to the list actually shipped.

These tests pin the claims that a code change can falsify. They deliberately do
NOT police prose - only facts with a counterpart in the source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from shared import institutions as inst

_ROOT = Path(__file__).resolve().parent.parent
_DOCS = _ROOT / "docs"


_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _page(name: str) -> str:
    """A page's RENDERED markup - comments stripped.

    Not tidiness: a comment is the natural place to explain why a claim is
    worded as it is, and those explanations quote the very strings under test.
    Scanning raw source therefore lets documentation satisfy the check.

    Measured, on the first version of this file: the login section carries a
    comment saying `id="login"` and why it exists, so
    `test_the_login_walkthrough_has_an_anchor` passed with the attribute
    DELETED - the one property it exists to protect. The architecture audit
    blanks comments before Rules 6 and 8 for the same reason.
    """
    return _COMMENT.sub("", (_DOCS / name).read_text(encoding="utf-8"))


_PAGES = sorted(p.name for p in _DOCS.glob("*.html"))


# ── The number on the marketing page ─────────────────────────────────────────

def test_every_quoted_institution_count_matches_the_shipped_list():
    """`build_institution_list.py` moves this number every time it runs - the
    list went 1,797 -> 4,272 -> 4,757 in one week. A stale count on the site is
    a small lie in the one paragraph whose job is to say "your school is
    probably in here", and nothing else would ever catch it."""
    shipped = inst.count()
    quoted = {}
    for name in _PAGES:
        for m in re.finditer(r"\b(\d,\d{3})\b\s*(?:<[^>]+>\s*)?verified schools", _page(name)):
            quoted.setdefault(name, []).append(m.group(1))
    assert quoted, (
        "no page quotes an institution count any more - if the claim was "
        "removed on purpose, remove this test with it"
    )
    wrong = {p: n for p, ns in quoted.items() for n in ns if n != f"{shipped:,}"}
    assert not wrong, (
        f"the site claims {wrong} but the app ships {shipped:,} institutions"
    )


# ── The login screen the site describes ──────────────────────────────────────

def test_no_page_says_the_login_lives_in_the_sidebar():
    """It is a full-page portal (`render_login_page`), and the sidebar does not
    render at all until you are authenticated."""
    for name in _PAGES:
        body = _page(name).lower()
        for m in re.finditer(r"sidebar", body):
            window = body[max(0, m.start() - 220):m.start() + 120]
            assert not re.search(r"canvas url|access token|log in to canvas", window), (
                f"{name} still describes logging in via the sidebar"
            )


def test_no_page_calls_the_help_tooltip_a_guide():
    """The "?" beside the token field is a tooltip answering "why is this
    needed / is it safe". Sending someone there for instructions leaves them
    reading two sentences that do not tell them what to do."""
    for name in _PAGES:
        for m in re.finditer(r"<strong>\?</strong>", _page(name)):
            window = _page(name)[m.start():m.start() + 260]
            assert "guide" not in window.lower(), (
                f"{name} points at the token tooltip for a step-by-step guide"
            )


def test_the_token_walkthrough_names_the_button_and_its_fallback():
    """The app opens the right Canvas page in one click, so the site must not
    teach the hunt as the only route - and must still say where that page is,
    because the button is the part that can fail."""
    for name in ("index.html", "guide.html"):
        body = _page(name)
        assert "Get a token" in body, f"{name} never mentions the one-click button"
        assert re.search(r"Account\s*(?:&#8594;|&rarr;|→|-&gt;)\s*Settings", body), (
            f"{name} does not say where the token page is without the button"
        )


def test_the_canvas_path_is_account_then_settings_everywhere():
    """Canvas's global nav item is "Account", and Settings lives inside it.
    "Account Settings" as one label is not a thing the user can click."""
    for name in _PAGES:
        assert "Account Settings" not in _page(name), (
            f"{name} says 'Account Settings' - the path is Account -> Settings"
        )


@pytest.mark.parametrize("name", ["index.html", "guide.html", "mac-setup.html"])
def test_the_pages_that_teach_login_agree_the_token_is_shown_once(name):
    """Every page that walks someone through generating a token has to carry
    this, because it is the only step with a cost: miss it and the token is
    unrecoverable - Canvas will not show it again.

    Matched as a PHRASE about the token. The first version of this test
    accepted the bare word "once", which appears on every page of the site for
    unrelated reasons ("once per update", "only once you are logged in") - it
    would have passed on a page that had lost the warning entirely."""
    body = _page(name)
    assert re.search(r"shows?\s+(?:the\s+token|it)\s+(?:only\s+)?once", body, re.I), (
        f"{name} lost the warning that Canvas shows the token once"
    )


# ── Anchors other pages depend on ────────────────────────────────────────────

def test_the_login_walkthrough_has_an_anchor_and_the_links_reach_it():
    """win-setup and mac-setup send people to the login walkthrough. Before the
    anchor existed those links landed on the FAQ, which answers a different
    question - and a wrong in-page link fails silently, because the page still
    loads."""
    # On the SECTION tag, not merely present in the file: an anchor is only an
    # anchor if it is on an element the browser can scroll to.
    assert re.search(r"<section[^>]*\bid=\"login\"", _page("index.html")), (
        "the login section lost its anchor"
    )
    linkers = [n for n in _PAGES if "index.html#login" in _page(n)]
    assert linkers, "nothing links to the login walkthrough any more"


def test_no_page_links_to_an_index_anchor_that_does_not_exist():
    """A dead in-page link scrolls nowhere and says nothing about it."""
    index = _page("index.html")
    ids = set(re.findall(r'id="([^"]+)"', index))
    missing = []
    for name in _PAGES:
        for anchor in re.findall(r'href="index\.html#([^"]+)"', _page(name)):
            if anchor not in ids:
                missing.append(f"{name} -> #{anchor}")
    assert not missing, f"dead links into index.html: {missing}"
