"""The site's text ramp, marker shapes and link colours, as a census.

Every check here is a CENSUS over every page found on disk, not a check that
one fix exists. That is deliberate: each defect below was present on between
twelve and twenty-five pages at once because the site is twenty-five separate
inline stylesheets with no shared file, so a fix that lands on the page you
happened to open is a fix that lands nowhere.

WHAT WAS WRONG, MEASURED IN A REAL BROWSER (Chromium, 2026-08-28)

*Body copy was dim and bold shouted.*  Seventeen pages set ``--txt2`` to
``#94a3b8``: 7.61:1 on the page background, against ``--txt``'s 15.82:1 for the
``<strong>`` sitting inside it.  Bold was **2.08x** the contrast of the sentence
it belonged to, which is why emphasis read as shouting rather than as emphasis.
On one article, 11,761 of ~15,500 rendered characters (76%) were that one dim
value.  The ramp is now 11.02 / 16.33, a **1.48x** step.

*Five ramps, not one.*  ``--txt2`` had four different values across the site and
``--txt3`` five, so the same paragraph rendered at a different brightness
depending on which page it was on.  ``guide.html`` set ``--txt3: #475569`` -
**2.57:1**, used for the entire thirty-entry sidebar table of contents.
``canvas-url-directory.html`` referenced a ``--muted`` variable that was never
defined, so five declarations were invalid at computed-value time and fell back
to inheriting full-strength ``--txt``.

*The blue tint.*  The whole ramp was Tailwind slate: ``#94a3b8`` has an
RGB spread of 36/255 and reads visibly cool, which clashes wherever the
background is not also blue (the amber and green callouts).  The replacement
holds the same hue at roughly a third of the chroma - spread 3 / 8 / 6.

*Circles and pills.*  Numbered and lettered step markers were drawn as filled
circles - the one shape this UI never uses; every other surface on the site and
in the app is a rounded rectangle.  Three step lists used three different
markers (a cyan circle, a grey circle, a rounded box).  Section kickers were
fully-round pills in four colours, and the blue variant put ``#3b71b8`` on the
page background at **3.94:1**, below the AA floor, on the words "Keep Your
Courses Up to Date".

*Links that were never given a colour.*  ``mac-setup.html`` had no ``a`` rule at
all, so "step-by-step walkthrough" rendered in the user agent's ``#0000EE`` at
**1.99:1** on a near-black card; ``canvas-url-directory.html`` had three more at
2.08:1.  Every other link on those pages had been coloured one at a time with an
inline ``style``, which is exactly why the ones that were missed looked broken
rather than merely off-palette.

WHAT IS NOT CHECKED HERE, AND WHY

Contrast ratios themselves are not recomputed - that needs a browser and the
real cascade, and the numbers above came from one.  What is checked is the
input a browser would use: that every page declares the same ramp, that no
retired value survives anywhere, and that no page reintroduces the shapes.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

#: The one text ramp, declared identically in all 25 ``:root`` blocks.
RAMP = {
    "--txt": "#e9ebee",    # headings, <strong>, table lead cells
    "--txt2": "#bfc3c9",   # body copy - the workhorse
    "--txt3": "#9599a1",   # captions, meta, kickers, step markers
}

#: Radius for a small boxed label. Same value as inline ``code``.
RAD_S = "5px"

#: Values the ramp used to hold, in every notation they appeared in. A page
#: that reintroduces one of these has gone back to a second palette.
RETIRED = (
    "#e2e8f0", "#94a3b8", "#cbd5e1", "#64748b", "#475569",
    "#a8b6c9", "#8494a8", "#b8cad8", "#8899a8", "#9fb0c6", "#93a3b8",
    "rgba(148, 163, 184", "rgba(148,163,184",
    "rgba(226, 232, 240", "rgba(226,232,240",
    "rgba(203, 213, 225", "rgba(203,213,225",
    "rgba(100, 116, 139", "rgba(100,116,139",
    "rgba(71, 85, 105", "rgba(71,85,105",
)

#: Selectors allowed to stay round. A dot, a knob, a radio, a spinner and a
#: blurred glow are round because of what they ARE; a tag is not.
ROUND_BY_NATURE = {
    ".hb-dot",                      # status dot in a floating hero badge
    ".history-row .h-dot",          # status dot in a sync-history row
    ".spinner",                     # a spinner has to be a circle
    ".close-modal",                 # round icon button, standard affordance
    ".today-mock-switch span",      # the knob of a toggle switch
    ".filter-btn .check",           # the app's own checkbox tick, reproduced
    ".struct-btn .check",
    ".cc-btn .check",
    ".pp-btn .check",
    ".quick-preset-card::before",   # the app's own radio button, reproduced
    ".proof-tag::before",           # a blurred radial glow, not a box
    "ul li::before",                # a bullet is a bullet
}

_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_RULE = re.compile(r"([^{}@]+)\{([^{}]*)\}")
_ROUND = re.compile(r"border-radius:\s*(?:50%|100px|999+px)")


def _pages():
    """Every page on disk. Derived, never hand-listed - a new page is covered
    the moment it exists, which is the whole point of a census."""
    return sorted(p.name for p in DOCS.glob("*.html"))


def _source(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def _css(name: str) -> str:
    """Every inline stylesheet, CSS comments stripped.

    The comments have to go: the fixes ship with comments that quote the very
    values and shapes these tests look for (``was #94a3b8``, ``border-radius:
    100px``), so without stripping them a page could pass on its own
    explanation, and commenting a rule out could not fail.
    """
    return "\n".join(_CSS_COMMENT.sub(" ", b) for b in _STYLE.findall(_source(name)))


def _rules(name: str):
    """``(selectors, declarations)`` for every innermost rule on the page.

    ``@media`` blocks fall out for free - the regex cannot match a block that
    still contains braces, so only innermost rules come back.
    """
    out = []
    for sel, decls in _RULE.findall(_css(name)):
        parts = [" ".join(s.split()) for s in sel.split(",") if s.strip()]
        if parts:
            out.append((parts, decls))
    return out


def _root_vars(name: str) -> dict:
    m = re.search(r":root\s*\{(.*?)\}", _css(name), re.S)
    if not m:
        return {}
    return {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1))}


def _key_parts(selector: str) -> set:
    """The bare element names a selector targets, pseudo-classes stripped.

    ``.faq-item summary:focus-visible`` -> ``{"summary"}``. Used to line up
    "what had its outline removed" against "what got a focus-visible ring",
    per element rather than per page.
    """
    out = set()
    for token in re.split(r"[\s>+~]+", selector.strip()):
        token = re.sub(r"::?[\w-]+(\([^)]*\))?", "", token)
        if token and re.fullmatch(r"[a-zA-Z][\w-]*", token):
            out.add(token.lower())
    return out


def _selectors_colouring_anchors(name: str):
    """What the cascade has available to give a link a colour.

    Returns two sets, and keeping them SEPARATE is the whole point:

    * ``descendant`` - selectors that END at an anchor (``a``, ``.art a``,
      ``footer a``). These are the only thing that can colour an anchor from
      the outside.
    * ``subject`` - selectors whose SUBJECT is the element itself and which
      set a colour (``.post``, ``a.post``). These only help an anchor that
      carries that class.

    Merging them was a real defect in this file's first draft: with one set,
    ``.setup-card { color: X }`` looked like it could colour a link inside a
    setup card, so ``mac-setup.html`` passed with its base ``a`` rule deleted.
    It cannot. The UA sheet's own ``a { color: -webkit-link }`` beats
    INHERITANCE, so a colour on an ancestor never reaches the anchor - which
    is exactly why the bug existed in the first place.

    ``:hover`` and friends are excluded: a colour that exists only on hover is
    not the colour the link has.
    """
    descendant, subject = set(), set()
    for sels, decls in _rules(name):
        if not re.search(r"(?<!-)\bcolor\s*:", decls):
            continue
        for sel in sels:
            if ":" in sel and "::" not in sel:
                continue  # a state, not the resting colour
            if sel == "a" or re.search(r"[\s>]a$", sel):
                descendant.add(sel)
                continue
            last = re.split(r"[\s>+~]+", sel.strip())[-1]
            if last.startswith("a."):
                last = last[1:]
            if last.startswith("."):
                subject.update(part for part in last.split(".") if part)
    return descendant, subject


class _AnchorScanner(HTMLParser):
    """Collect every anchor with no inline colour, plus its context.

    Two kinds are collected and they are not the same question:

    * an anchor with NO class - the only thing that can reach it is a bare
      ``a`` rule or a ``<ancestor> a`` rule, so the ancestor chain is what
      matters (the site uses both ``footer a`` and ``.art a``);
    * an anchor WITH a class - its own class rule may colour it, so its own
      classes go in the chain too. ``blog.html``'s twelve post cards are each
      one big ``a.post``, and ``.post`` set every property EXCEPT colour, so
      all twelve computed to the UA's ``#0000EE``. Nothing rendered blue only
      because every text node inside them happened to set its own colour -
      luck, not a rule. Skipping classed anchors would leave that unguarded.
    """

    #: Void elements never push a scope; ``path``/``source`` appear inside the
    #: inline SVG icons and are self-closing in this markup.
    VOID = ("br", "img", "input", "hr", "meta", "link", "source", "path",
            "polyline", "polygon", "circle", "line", "rect", "use")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.found = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            style = (attrs.get("style") or "").lower()
            if "color" not in style:
                own = set((attrs.get("class") or "").split())
                # Descendant selectors that could reach this anchor, in the
                # same vocabulary _selectors_colouring_anchors returns.
                reach = {"a"}
                for anc_tag, anc_classes in self.stack:
                    reach.add(f"{anc_tag} a")
                    reach.update(f".{c} a" for c in anc_classes)
                self.found.append((own, reach, (attrs.get("href") or "")[:60]))
        if tag not in self.VOID:
            self.stack.append((tag, (attrs.get("class") or "").split()))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def _bare_anchor_contexts(name: str):
    src = _HTML_COMMENT.sub("", _source(name))
    src = _STYLE.sub("", src)
    src = re.sub(r"<script[^>]*>.*?</script>", "", src, flags=re.S)
    p = _AnchorScanner()
    p.feed(src)
    return p.found


# --------------------------------------------------------------------------
# One ramp, everywhere
# --------------------------------------------------------------------------

@pytest.mark.parametrize("page", _pages())
def test_page_declares_the_one_text_ramp(page):
    """Every page's ``:root`` holds the same three values.

    This is the check that would have caught the drift: four ``--txt2`` values
    and five ``--txt3`` values across twenty-five pages, including a 2.57:1
    ``--txt3`` on the guide's sidebar.
    """
    got = _root_vars(page)
    for var, want in RAMP.items():
        assert got.get(var) == want, (
            f"{page} declares {var}: {got.get(var)!r}, expected {want!r}. "
            "The ramp is one ramp; a second value here is a second palette."
        )


@pytest.mark.parametrize("page", _pages())
def test_page_declares_the_small_radius_token(page):
    assert _root_vars(page).get("--rad-s") == RAD_S, (
        f"{page} is missing --rad-s: {RAD_S}. Small boxed labels resolve it, "
        "so a page without it renders them with no radius at all."
    )


@pytest.mark.parametrize("page", _pages())
def test_no_page_reintroduces_a_retired_ramp_value(page):
    """No copy of the old palette survives anywhere on the page.

    Deliberately over the WHOLE source, not just ``<style>``: the retired
    values were also sitting in ``stroke=`` attributes on inline SVG icons, in
    an inline ``style`` attribute, and inside an ``onmouseout`` handler that
    restored a colour in JavaScript. A stylesheet-only check passed all four.
    """
    src = _HTML_COMMENT.sub("", _source(page))
    src = _CSS_COMMENT.sub(" ", src)
    for dead in RETIRED:
        assert dead.lower() not in src.lower(), (
            f"{page} still contains the retired ramp value {dead!r}. "
            "It disagrees with the token now."
        )


def test_the_wizard_stylesheet_tracks_the_same_ramp():
    """``mac-wizard.css`` is a SECOND copy of the scale, under ``--mw-`` names.

    It is a separate file with its own variable block, so it does not appear in
    any ``:root`` census above and drifted independently once already
    (``#b8cad8`` / ``#8899a8``).
    """
    css = _CSS_COMMENT.sub(" ", (DOCS / "mac-wizard.css").read_text(encoding="utf-8"))
    got = dict(re.findall(r"(--mw-txt[23]?)\s*:\s*([^;]+);", css))
    assert got.get("--mw-txt", "").strip() == RAMP["--txt"]
    assert got.get("--mw-txt2", "").strip() == RAMP["--txt2"]
    assert got.get("--mw-txt3", "").strip() == RAMP["--txt3"]


# --------------------------------------------------------------------------
# Shapes: a marker is a character, a tag is a rounded rectangle
# --------------------------------------------------------------------------

@pytest.mark.parametrize("page", _pages() + ["mac-wizard.css"])
def test_nothing_new_is_round(page):
    """Census, not a spot check: any rule that is round must be on the list.

    Written this way on purpose. A test that asserted "``.steps > li::before``
    is not a circle" would pass while a new circle appeared beside it; this one
    fails on any unclassified round rule, which is what makes it worth having.
    """
    if page.endswith(".css"):
        css = _CSS_COMMENT.sub(" ", (DOCS / page).read_text(encoding="utf-8"))
        rules = [([" ".join(s.split()) for s in sel.split(",") if s.strip()], decls)
                 for sel, decls in _RULE.findall(css)]
    else:
        rules = _rules(page)

    offenders = sorted({sel for sels, decls in rules if _ROUND.search(decls)
                        for sel in sels if sel not in ROUND_BY_NATURE})
    assert not offenders, (
        f"{page} has round rules that are not on the allow-list: {offenders}. "
        "A number or a letter is a character, not a graphic; a tag is a "
        "rounded rectangle like every other box in this UI. If one of these "
        "really is a dot, a knob, a radio or a spinner, add it to "
        "ROUND_BY_NATURE with the reason."
    )


@pytest.mark.parametrize("page", _pages())
def test_step_markers_carry_a_period_and_no_box(page):
    """Where a step marker exists it is mono type in a gutter, not a chip."""
    for sels, decls in _rules(page):
        for sel in sels:
            if not re.search(r"\b(steps|step-n|step-num|perm-num|\.num)\b", sel):
                continue
            if "content:" in decls and "counter(" in decls:
                assert "mono" in decls, (
                    f"{page} {sel}: a step marker is set in the mono face, which "
                    "is what distinguishes it from the sentence without drawing "
                    "anything around it."
                )
                assert "border:" not in decls and "background:" not in decls, (
                    f"{page} {sel}: the marker is the character. A border or a "
                    "fill puts the chip back."
                )


# --------------------------------------------------------------------------
# Links and focus
# --------------------------------------------------------------------------

@pytest.mark.parametrize("page", _pages())
def test_every_anchor_is_reachable_by_some_colour_rule(page):
    """Every ``<a>`` without an inline colour has a rule that can colour it.

    Two earlier versions of this check were too loose, and both misses are
    worth keeping in view because they are the same mistake at two depths:

    1. Asking whether the page had ANY rule with "a", "link" or "btn" in the
       selector. ``mac-setup.html`` - the page the defect was FOUND on -
       passed on the strength of its own ``.nav-link`` and ``.btn-nav`` rules
       while the broken prose link sat right there.
    2. Merging "rules ending at an anchor" with "rules on some ancestor's
       class" into one set, so ``.setup-card { color: X }`` looked like it
       could colour a link inside a setup card. It cannot: the UA's own
       ``a { color: -webkit-link }`` beats inheritance, which is precisely why
       an un-styled link renders blue on a dark page in the first place.

    So the anchor's OWN classes and its ANCESTORS are asked different
    questions, which is what makes the mutant fail.
    """
    anchors = _bare_anchor_contexts(page)
    if not anchors:
        pytest.skip("no anchors on this page")

    descendant, subject = _selectors_colouring_anchors(page)
    if "a" in descendant:
        return  # a base rule covers everything

    unreached = [
        href for own, reach, href in anchors
        if not (own & subject) and not (reach & descendant)
    ]
    assert not unreached, (
        f"{page}: {len(unreached)} anchor(s) have no inline colour and no rule "
        f"that can colour them - so they render in the user agent's #0000EE "
        f"(measured 1.99:1 on this site's background). First: {unreached[0]!r}. "
        "Give the page a base `a` rule rather than colouring one more link "
        "inline; the ones that get missed are the ones that look broken."
    )


@pytest.mark.parametrize("page", _pages())
def test_suppressed_focus_rings_are_replaced(page):
    """``outline: none`` is fine; ``outline: none`` with nothing to replace it is not.

    Both pages that used it did so to stop a ``<summary>`` keeping a ring after
    a mouse click - a real problem. But it took the ring away from the keyboard
    too, and a ``<summary>`` is the only way to open those accordions with one.
    Tabbing the real pages: 11 of 70 stops on ``guide.html`` and 30 of 69 on
    ``index.html`` had no focus indicator at all. ``:focus-visible`` does not
    match a mouse click, so it restores the keyboard ring and leaves the click
    behaviour the ``outline: none`` was protecting untouched.

    The check is per-ELEMENT, not per-page. Asking only whether the string
    ``:focus-visible`` appears anywhere let a mutant that dropped ``summary``
    from the ring's selector list pass, because the rule still covered
    ``button``.
    """
    silenced = set()
    for sels, decls in _rules(page):
        if not re.search(r"outline:\s*(none|0)\b", decls):
            continue
        for sel in sels:
            silenced.update(_key_parts(sel))

    if not silenced:
        return

    covered = set()
    for sels, decls in _rules(page):
        # `outline` as a PROPERTY, not the substring: `outline-offset: 3px`
        # contains it, so a ring reduced to nothing but its offset passed.
        if not re.search(r"(?<![-\w])outline\s*:", decls):
            continue
        if re.search(r"(?<![-\w])outline\s*:\s*(none|0)\b", decls):
            continue  # this rule REMOVES a ring, it does not provide one
        for sel in sels:
            if ":focus-visible" in sel:
                covered.update(_key_parts(sel.replace(":focus-visible", "")))

    missing = sorted(silenced - covered)
    assert not missing, (
        f"{page} silences the focus ring on {missing} but no :focus-visible "
        "rule sets an outline for them, so keyboard users get no indicator."
    )


@pytest.mark.parametrize("page", _pages())
def test_the_label_collapse_is_scoped_to_the_nav(page):
    """Hiding a button's label on a narrow screen is right in the nav, wrong outside it.

    In the nav each button also carries an SVG, so dropping the words leaves a
    glyph. The article CTA box reuses ``.btn-nav-ghost`` for a text-only link:
    unscoped, the rule left an empty 22x37px box on a 390px viewport, on all
    twelve article pages ("See it in action", "Compare all methods",
    "Acceptable use").

    Every selector in the rule is checked, not the text around it. Looking for
    the substring ``"nav "`` passed the unscoped form, because ``.btn-nav span``
    contains it.
    """
    for sels, decls in _rules(page):
        if "display: none" not in decls and "display:none" not in decls:
            continue
        for sel in sels:
            if not re.search(r"\.btn-nav(-ghost)?\s+span\b", sel):
                continue
            assert sel.startswith("nav "), (
                f"{page}: {sel!r} hides a button label but is not scoped to the "
                "nav. Outside the nav there is no icon left behind, only an "
                "empty box."
            )
