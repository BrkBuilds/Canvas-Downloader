"""The Store listing copy fits, and the generated page has not gone stale.

WHY THIS FILE EXISTS
--------------------
Two hazards, both of which this project has already been bitten by under other
names.

**1. A GENERATED file that is also CHECKED IN ships whatever was last
committed.** ``CLAUDE.md`` records this for ``version_info.py``: the spec copies
it into the bundle, so the artifact carries whatever the file said at build
time, and nothing reports the mismatch. ``marketing/store-listing.html`` and
``store-listing.artifact.html`` are rendered from ``marketing/STORE_LISTING.md``
by ``marketing/build_store_page.py``, and they are tracked so the page opens on
any machine without running Python. Edit the markdown, forget to regenerate, and
somebody pastes last week's copy into Partner Center. The first test below makes
that fail in the commit that causes it.

**2. A character limit is a fact about the Store, not about the copy.** Partner
Center rejects an over-length field at submission time, which is the worst
moment to discover it: the whole submission is already filled in. The limits are
quoted from Microsoft's current documentation in ``STORE_LISTING.md`` section 3,
and asserted here so an edit that overflows one fails immediately.

WHAT IS DELIBERATELY *NOT* ASSERTED
The wording. Copy is a judgment call and belongs to the product owner; these
tests check that it fits, that it is paste-safe, and that the rendered page
agrees with it. A test that pinned the sentences would fail on every legitimate
edit and would teach people to delete it.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MARKETING = REPO / "marketing"
SOURCE = MARKETING / "STORE_LISTING.md"
GENERATED = (MARKETING / "store-listing.html", MARKETING / "store-listing.artifact.html")


def _builder():
    """Import marketing/build_store_page.py by path (it is not a package).

    The tests take their block anchors from the builder's own ``FIELDS`` map
    rather than restating them. Two copies of one anchor is the defect this
    repository has hit under a dozen names; when the owner rewrote the
    description on 2026-08-24 the opener changed, and a duplicated anchor would
    have had to be found and fixed in two files or the suite would have failed
    with "expected exactly one fenced block" - which reads like a broken
    document rather than a stale test.
    """
    path = MARKETING / "build_store_page.py"
    spec = importlib.util.spec_from_file_location("_build_store_page", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _blocks() -> list[str]:
    md = SOURCE.read_text(encoding="utf-8")
    return [b.strip("\n") for b in re.findall(r"^```[a-z]*\n(.*?)^```", md, re.S | re.M)]


def _field(prefix: str) -> str:
    hits = [b for b in _blocks() if b.startswith(prefix)]
    assert len(hits) == 1, (
        f"expected exactly one fenced block starting {prefix!r} in STORE_LISTING.md, "
        f"found {len(hits)}. Re-anchor rather than loosening the match - the "
        f"generator resolves the same blocks the same way.")
    return hits[0]


def _anchor(token: str) -> str:
    """The block anchor the GENERATOR uses for this field. Single source."""
    prefix = _builder().FIELDS[token]
    assert prefix, f"{token} has no anchor in build_store_page.FIELDS"
    return prefix


# ── 1. the page is in sync with its source ──────────────────────────────────

def test_the_generated_page_matches_STORE_LISTING_md(tmp_path, monkeypatch):
    """Regenerate into a temp dir and compare with what is committed.

    The failure message has to say *what to do*, because the fix is one command
    and the symptom (a stale page) is otherwise indistinguishable from a page
    somebody edited by hand.
    """
    mod = _builder()
    monkeypatch.setattr(mod, "OUT_ARTIFACT", tmp_path / "artifact.html")
    monkeypatch.setattr(mod, "OUT_STANDALONE", tmp_path / "standalone.html")
    assert mod.main() == 0

    fresh = {
        MARKETING / "store-listing.artifact.html": tmp_path / "artifact.html",
        MARKETING / "store-listing.html": tmp_path / "standalone.html",
    }
    for committed, rendered in fresh.items():
        assert committed.exists(), f"{committed.name} is missing - run: python marketing/build_store_page.py"
        assert committed.read_text(encoding="utf-8") == rendered.read_text(encoding="utf-8"), (
            f"{committed.name} is out of date with marketing/STORE_LISTING.md.\n"
            f"Run:  python marketing/build_store_page.py\n"
            f"and commit the result. Do not hand-edit the generated pages - the "
            f"markdown is the source of truth.")


def test_the_generated_pages_are_tracked_and_present():
    for path in GENERATED:
        assert path.exists(), f"{path.name} missing; run python marketing/build_store_page.py"


def test_the_standalone_copy_is_a_complete_document():
    """Without a doctype the browser uses QUIRKS MODE, i.e. a different box model.

    The artifact source must NOT carry one (the Artifact tool supplies the
    skeleton); the on-disk copy must. Both halves are asserted, because getting
    either backwards produces a page that looks fine in one place and wrong in
    the other.
    """
    standalone = (MARKETING / "store-listing.html").read_text(encoding="utf-8")
    artifact = (MARKETING / "store-listing.artifact.html").read_text(encoding="utf-8")
    assert standalone.lstrip().lower().startswith("<!doctype html>")
    assert "<html lang=" in standalone and 'charset="utf-8"' in standalone
    assert "<!doctype" not in artifact.lower()
    assert "<html" not in artifact.lower()


def test_the_page_loads_nothing_from_a_third_party_host():
    """The artifact CSP admits Google Fonts and nothing else, and the on-disk
    copy has to open with no network at all beyond that."""
    for path in GENERATED:
        text = path.read_text(encoding="utf-8")
        urls = re.findall(r'(?:src|href)="(https?://[^"]+)"', text)
        foreign = [u for u in urls
                   if not u.startswith(("https://fonts.googleapis.com",
                                        "https://fonts.gstatic.com"))]
        assert not foreign, f"{path.name} loads assets from {foreign}"


# ── 2. every field still fits its Store limit ───────────────────────────────
# Limits quoted from Microsoft's current listing documentation. `soft` is the
# number of characters actually SHOWN, where that differs from the hard cap.

@pytest.mark.parametrize("name,token,hard,soft", [
    # The short description IS a Partner Center field - it sits under
    # Supplemental fields, which is collapsed by default, so a look at the page
    # reported it missing on 2026-08-24. 1,000 hard, ~270 actually shown.
    ("short description", "SHORT",     1000, 270),
    ("description",       "DESC",     10000, None),
    ("what's new",        "WHATSNEW",  1500, None),
    ("copyright info",    "COPYRIGHT",  200, None),
])
def test_field_fits_its_limit(name, token, hard, soft):
    body = _field(_anchor(token))
    assert len(body) <= hard, f"{name}: {len(body)} chars, limit {hard}"
    if soft is not None:
        assert len(body) <= soft, (
            f"{name}: {len(body)} chars. The field allows {hard}, but only the "
            f"first {soft} are shown, so the rest is invisible in most views.")


def test_product_features_fit():
    items = [l for l in _field(_anchor("FEATURES")).split("\n") if l.strip()]
    assert len(items) <= 20, f"{len(items)} features, max 20"
    for item in items:
        assert len(item) <= 200, f"feature over 200 chars: {item!r}"
        assert not item.lstrip().startswith(("-", "*", "•")), (
            f"Partner Center bullets these itself; a leading bullet double-bullets "
            f"the line: {item!r}")


def test_keywords_fit_the_word_budget():
    """7 terms, 40 chars each, and - the one people miss - no more than 21
    separate WORDS across all of them."""
    terms = [l.strip() for l in _field(_anchor("KEYWORDS")).split("\n") if l.strip()]
    assert len(terms) <= 7, f"{len(terms)} keywords, max 7"
    for t in terms:
        assert len(t) <= 40, f"keyword over 40 chars: {t!r}"
    words = sum(len(t.split()) for t in terms)
    assert words <= 21, f"{words} words across the keywords, max 21"


def test_screenshot_captions_fit():
    caps = [l for l in _field("1  Tick your courses").split("\n") if l.strip()]
    assert len(caps) == 8, f"{len(caps)} captions, expected one per screenshot"
    for line in caps:
        text = re.sub(r"^\d+\s+", "", line)
        assert len(text) <= 200, f"caption over 200 chars: {text[:60]!r}..."


# ── 3. the description is paste-safe and on-voice ───────────────────────────

def test_the_description_is_paste_safe():
    """Three properties that are invisible on screen and cost a submission.

    ASCII-only matters because the copy is pasted into a web form: the live
    listing's bullets survived, but a smart quote or a dash that arrives as a
    different code page is exactly the mojibake this repo already documents for
    CP1252 file writes. Em dashes are a standing house rule. And Microsoft's own
    guidance says not to put URLs in the description field, which is why the
    source offer lives in Additional license terms instead.
    """
    desc = _field(_anchor("DESC"))
    non_ascii = sorted({c for c in desc if ord(c) > 127})
    assert not non_ascii, f"description contains non-ASCII: {non_ascii}"
    assert "—" not in desc, "em dash in the description - house rule is ' - '"
    assert "http://" not in desc and "https://" not in desc, (
        "Microsoft: 'Do not include HTML, code snippets, or URLs in the "
        "description field.' The GPL source URL belongs in Additional license "
        "terms, which explicitly renders a single URL as a link.")


def test_LMS_appears_only_in_the_legal_disclaimer():
    """STRATEGY.md: students say 'Canvas', never 'LMS'. The one permitted use is
    the affiliation disclaimer, which is legal-style wording rather than copy
    aimed at a student."""
    desc = _field(_anchor("DESC"))
    hits = re.findall(r"\bLMS\b", desc)
    assert len(hits) == 1, f"'LMS' appears {len(hits)} times in the description"
    # Locate the PARAGRAPH, not a character window and not a "sentence".
    # Two brittle anchors were tried first and both reported correct copy as a
    # violation: a 60-character lookback (the words "not affiliated" sit ~75
    # characters before "LMS"), then a split on ". " (which breaks the
    # disclaimer at "Instructure, Inc."). A paragraph has an unambiguous
    # delimiter, so it cannot be wrong about where the sentence ends.
    para = next(p for p in desc.split("\n\n") if "LMS" in p)
    assert "not affiliated" in para.lower(), (
        f"the one permitted 'LMS' is the affiliation disclaimer; this one is "
        f"somewhere else: {para!r}")


def test_the_gpl_source_location_is_stated_somewhere_in_the_description():
    """GPLv3 section 6 duty. The clickable offer is in Additional license terms,
    but the description must still name where the source is - a reader of the
    listing text alone should be able to find it."""
    desc = _field(_anchor("DESC"))
    assert "github.com/BrkBuilds/Canvas-Downloader" in desc
    assert "General Public License" in desc


def test_the_store_product_id_matches_the_app():
    """The listing document quotes the product id in its verification command.
    If a re-listing ever mints a new id, this fails alongside the app's own
    pinned copy rather than silently pointing at a dead product."""
    from core.store_review import STORE_PRODUCT_ID
    md = SOURCE.read_text(encoding="utf-8")
    assert STORE_PRODUCT_ID in md, (
        f"marketing/STORE_LISTING.md does not mention the Store product id "
        f"{STORE_PRODUCT_ID!r} that the app links to.")
