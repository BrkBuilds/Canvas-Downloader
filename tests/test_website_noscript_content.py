"""A page's own text must not be ``opacity: 0`` to a crawler that runs no JavaScript.

Nearly every block on the homepage and the guide carries ``class="reveal"``,
which an IntersectionObserver un-hides by adding ``.vis``. Measured with a real
parser before this was fixed, words inside a ``.reveal`` as a share of each
page's body text:

    guide.html    7,025 / 7,217   (97%)   h1 hidden
    index.html    3,125 / 4,112   (75%)   h1 hidden
    engine.html      59 / 3,491   ( 1%)   h1 hidden

Google renders JavaScript, so Google is probably unaffected. Several assistant
crawlers do not. ``marketing/FINDINGS.md`` records that the site "appeared in
zero of three web searches" and that "when a search assistant summarised the
product it quoted the Store copy, not the site" - a homepage whose ``h1`` and
three quarters of whose text are invisible to a non-rendering fetch is a
plausible contributing cause.

THE FIX IS ADDITIVE, AND THAT IS THE POINT. The animation is part of the page's
design and has been tuned around; it is not deleted and the existing rules are
not touched. One rule is ADDED::

    html:not(.js) .reveal { opacity: 1; transform: none; }

plus one inline ``<head>`` script that sets the class. With JavaScript present
``html.js`` matches, so ``html:not(.js)`` never applies and the animated path is
byte-identical - verified in a real browser against the deployed (pre-fix) site:
same reveal count, same initially-hidden count, same per-element
``transitionDelay`` ladder, same computed transition, and 0 hidden after
scrolling, on both index and guide.

TWO DETAILS THAT LOOK COSMETIC AND ARE NOT:

* **Specificity.** ``html:not(.js) .reveal`` is (0,2,1) and beats the plain
  ``.reveal`` (0,1,0) with no ``!important``. Inverting the fix instead - moving
  the hide onto ``html.js .reveal`` - would ALSO outrank ``.reveal.vis`` (0,2,0),
  so nothing would ever become visible again. That failure is invisible in
  review and total in a browser, which is why the additive form is the one
  guarded here.
* **The class means "the mechanism that reveals this exists"**, not merely
  "scripting is on" - it is set only when ``IntersectionObserver`` is present.
  A browser with scripting but no observer would otherwise hide the page and
  never un-hide it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

#: Every page that hides content behind ``.reveal``. Derived, not hand-listed -
#: see ``test_the_page_list_is_derived_from_the_markup``.
# engine.html left this list on 2026-08-31: its only two .reveal elements were
# the hero h1 and lede, removed because an element at opacity 0 is not a paint
# and they were delaying LCP (4260 -> 3810 ms, measured n=2, spread 0). It now
# has zero, so there is nothing on it for the no-JS rule to un-hide.
GATED_PAGES = ("index.html", "guide.html")

_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _source(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def _markup(name: str) -> str:
    """Source with HTML comments removed.

    The fix ships with an explanatory comment that quotes the very rule these
    tests look for. Without this, commenting the rule out would still pass.
    """
    return _COMMENT.sub("", _source(name))


_REVEAL_CLASS = re.compile(r'class="[^"]*\breveal\b[^"]*"')


def _pages_using_reveal():
    """Pages carrying at least one element in the .reveal class.

    This matched the PREFIX `class="reveal` until 2026-08-31, so it only saw
    elements where reveal is the FIRST class. guide.html has 136 of the form
    `class="body-text reveal"` and none of the first form, so removing its two
    prefix-matching elements dropped the whole page out of the census while 136
    gated elements were still on it. A guard that a class-attribute REORDER can
    switch off is the exact failure its own docstring warns about.
    """
    return sorted(p.name for p in DOCS.glob("*.html")
                  if _REVEAL_CLASS.search(_markup(p.name)))


_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _css(name: str) -> str:
    """Every inline stylesheet on the page, with CSS comments removed.

    Scoped to ``<style>`` on purpose: run over the whole document, the text
    before a ``{`` is everything since the previous brace - markup included -
    so a selector never compares equal to itself. CSS comments have to go for
    the same reason (``/* reveal */`` sits directly above the rule on two of
    the three pages), and separately so that commenting a rule out cannot pass.
    """
    return "\n".join(_CSS_COMMENT.sub(" ", b) for b in _STYLE.findall(_source(name)))


def _rules(name: str):
    """Every ``selector-list { declarations }`` in the page, selectors split.

    Nested at-rules (``@media``) fall out for free: the regex cannot match a
    block that still contains braces, so only the innermost rules are returned.

    Selectors are compared WHOLE. A suffix or lookbehind match is what let the
    inverted form (`html.js .reveal.vis`) survive the first version of this
    file's positive control - it still ends in `.reveal.vis`, and that inversion
    is precisely the change that would stop anything ever being revealed.
    """
    out = []
    for sel, decls in _RULE.findall(_css(name)):
        parts = [s.strip() for s in sel.split(",") if s.strip()]
        if parts:
            out.append((parts, decls))
    return out


def _has_rule(name: str, selector: str, needle: str) -> bool:
    return any(selector in sels and needle in decls
               for sels, decls in _rules(name))


# ── the list this file guards is the real one ────────────────────────────────

def test_the_page_list_is_derived_from_the_markup():
    """A hand-maintained list silently stops covering a page that gains
    ``.reveal`` later - which is the same 'a fix landed on two of three sites'
    shape this repo has been bitten by. Fail loudly instead."""
    assert _pages_using_reveal() == sorted(GATED_PAGES), (
        f"pages using .reveal changed: {_pages_using_reveal()} - add the "
        "no-JS rule and the head script to any new one, then update GATED_PAGES")


# ── the rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("page", GATED_PAGES)
def test_content_is_not_hidden_when_scripting_is_absent(page):
    css = _css(page)   # CSS comments stripped: /* ...the rule... */ must not pass
    assert re.search(r"html:not\(\.js\)\s+\.reveal\s*{[^}]*opacity:\s*1", css), (
        f"{page} hides .reveal unconditionally - a non-rendering fetch gets "
        "opacity: 0 for most of the page")


@pytest.mark.parametrize("page", GATED_PAGES)
def test_the_no_js_rule_also_undoes_the_transform(page):
    """``opacity: 1`` alone leaves the 20px offset, so a no-JS render is every
    block nudged down - and anything measuring layout sees the wrong geometry."""
    m = re.search(r"html:not\(\.js\)\s+\.reveal\s*{([^}]*)}", _css(page))
    assert m, f"{page} has no no-JS reveal rule at all"
    assert "transform" in m.group(1) and "none" in m.group(1), (
        f"{page}'s no-JS rule does not reset transform: {m.group(1)!r}")


@pytest.mark.parametrize("page", GATED_PAGES)
def test_the_existing_reveal_rules_are_untouched(page):
    """The animated path must stay exactly what it was.

    If the hide is ever moved onto ``html.js .reveal`` it outranks
    ``.reveal.vis`` and nothing is ever revealed again. Pin the plain, unscoped
    forms so that inversion cannot be made quietly.
    """
    assert _has_rule(page, ".reveal", "opacity: 0"), (
        f"{page} no longer has the plain `.reveal {{ opacity: 0 }}` rule")
    assert _has_rule(page, ".reveal.vis", "opacity: 1"), (
        f"{page}'s `.reveal.vis` rule is no longer written as a bare selector. "
        "If the hide was moved onto `html.js .reveal` (0,2,1), it outranks "
        "`.reveal.vis` (0,2,0) and NOTHING is ever revealed again.")
    assert not any(any(sel.startswith("html.js") for sel in sels)
                   for sels, _ in _rules(page)), (
        f"{page} scopes a rule to `html.js` - the fix is additive on "
        "`html:not(.js)` precisely so the animated path keeps its specificity")


# ── the class that arms it ───────────────────────────────────────────────────

@pytest.mark.parametrize("page", GATED_PAGES)
def test_the_js_class_is_set_from_an_inline_head_script(page):
    """It must be inline and in ``<head>``.

    An external or deferred script runs after first paint, so the page would
    render visible and then blink out before the observer restored it - a worse
    result than the bug being fixed.
    """
    source = _source(page)
    head_open = source.index("<head>")
    head_close = source.index("</head>")
    setter = re.search(r"documentElement\.classList\.add\(\s*['\"]js['\"]\s*\)", source)
    assert setter, f"{page} never sets the .js class, so nothing is ever animated"
    assert head_open < setter.start() < head_close, (
        f"{page} sets the .js class outside <head> - it must run before first paint")
    assert "src=" not in source[head_open:setter.start()].split("<script")[-1], (
        f"{page} sets the .js class from an external script")


@pytest.mark.parametrize("page", GATED_PAGES)
def test_the_class_is_gated_on_the_observer_that_does_the_revealing(page):
    """``.js`` means "the thing that will un-hide this content exists".

    The reveal script calls ``new IntersectionObserver`` with no fallback, so on
    a browser without it the constructor throws and nothing is ever revealed.
    Setting the class unconditionally would hide the page for those visitors
    permanently.
    """
    source = _source(page)
    setter = re.search(
        r"if\s*\(\s*['\"]IntersectionObserver['\"]\s+in\s+window\s*\)\s*"
        r"document\.documentElement\.classList\.add\(\s*['\"]js['\"]\s*\)", source)
    assert setter, (
        f"{page} sets the .js class without checking IntersectionObserver - a "
        "browser without it would hide the page and never reveal it")


@pytest.mark.parametrize("page", GATED_PAGES)
def test_the_reveal_observer_still_exists_to_be_gated_on(page):
    """Keeps every assertion above from going vacuous.

    If a page stops using an IntersectionObserver to reveal, the gate is
    reasoning about a mechanism that is no longer there.
    """
    assert "IntersectionObserver" in _source(page)


# ── the h1 specifically ──────────────────────────────────────────────────────

@pytest.mark.parametrize("page", GATED_PAGES)
def test_the_h1_is_reachable_without_javascript(page):
    """The single most valuable string on the page for search and for an
    assistant summarising the product. All three had it inside a ``.reveal``."""
    assert re.search(r"html:not\(\.js\)\s+\.reveal", _css(page)), (
        f"{page}'s h1 may sit inside a .reveal and there is no no-JS rule")
