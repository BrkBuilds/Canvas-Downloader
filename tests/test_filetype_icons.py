"""The filetype icon set: coverage, well-formedness, and the legibility floor.

The defect this guards is COVERAGE FALLING BEHIND THE ENGINE. The set it
replaced had 18 keys while the app could put far more than 18 extensions on
screen - ``.md`` and ``.srt`` are outputs this app PRODUCES, ``.pptm``/``.pot``/
``.potx`` are admitted by even the most restrictive file filter, and ten of the
extensions the pill whitelist named itself had no icon at all. Every one of them
rendered as a blank grey page, silently, next to a label naming the type.

So the coverage tests do not carry a hand-written list of extensions - they read
the ENGINE's own sources (``STUDY_FILE_EXTENSIONS``, ``_EFFECTIVE_EXT_MAP``,
``CODE_EXTENSIONS``, the Panopto kinds, the shortcut suffixes). A list written
here would be the same divergent copy that caused the bug.
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET

import pytest

from shared.filetype_icons import (
    FILETYPE_SVGS,
    FILETYPE_SVG_DEFAULT,
    _FAMILIES,
    _GLYPH_RISE,
    _GLYPHS,
    _ft_icon,
    _mix,
)


def _svg_of(uri: str) -> str:
    assert uri.startswith("data:image/svg+xml,"), uri[:40]
    return urllib.parse.unquote(uri.split(",", 1)[1])


# --- Coverage, read from the engine rather than restated ---------------------

def _engine_extensions() -> set[str]:
    """Every extension the app can produce or admit, from the engine's sources."""
    from core.canvas_logic import STUDY_FILE_EXTENSIONS
    from converters.code import CODE_EXTENSIONS
    from shared.helpers import _EFFECTIVE_EXT_MAP

    exts: set[str] = set(STUDY_FILE_EXTENSIONS) | set(CODE_EXTENSIONS)
    for _key, srcs, target in _EFFECTIVE_EXT_MAP:
        exts |= set(srcs)
        exts.add(target)
    # Panopto output kinds. 'url' is the Shortcut output and lands on disk as
    # .url (Windows) or .webloc (macOS) - see panopto/shortcut.py.
    exts |= {".mp4", ".mp3", ".txt", ".srt", ".url", ".webloc"}
    # Canvas secondary content is exported as HTML.
    exts.add(".html")
    return {e.lstrip(".").lower() for e in exts}


def test_every_extension_the_engine_can_produce_has_its_own_icon():
    missing = sorted(e for e in _engine_extensions() if e not in FILETYPE_SVGS)
    assert not missing, (
        "these reach the UI and would render as a blank grey page: " + ", ".join(missing)
    )


@pytest.mark.parametrize("ext", ["md", "srt", "webloc", "pptm", "pot", "potx", "py", "sql", "json"])
def test_the_extensions_that_had_no_icon_before_have_one_now(ext):
    """Named individually because each was a separately-reachable defect."""
    assert ext in FILETYPE_SVGS
    assert FILETYPE_SVGS[ext] != FILETYPE_SVG_DEFAULT


def test_the_pill_whitelist_is_derived_from_the_icon_table_not_restated():
    """A second hand-kept list is what put a blank icon under a "PY" label.

    Asserted on behaviour rather than on the source text: every extension the
    pill code will give its own bucket must resolve to a real icon.
    """
    from shared.components import _build_filetype_pills_html

    html = _build_filetype_pills_html(
        ["a.py", "b.py", "c.md", "d.md", "e.srt", "f.srt", "g.webloc", "h.webloc"]
    )
    assert FILETYPE_SVG_DEFAULT not in html, (
        "a named filetype pill fell back to the unknown icon"
    )
    for label in ("PY", "MD", "SRT", "WEBLOC"):
        assert label in html


def test_an_unknown_extension_still_gets_a_page_not_nothing():
    html_uri = FILETYPE_SVGS.get("no-such-ext", FILETYPE_SVG_DEFAULT)
    svg = _svg_of(html_uri)
    assert "<path" in svg and "<rect" in svg, "the unknown icon must still read as a file"


# --- Well-formedness --------------------------------------------------------

def test_every_icon_is_a_parseable_svg():
    for ext, uri in sorted(FILETYPE_SVGS.items()):
        ET.fromstring(_svg_of(uri))  # raises on malformed markup
    ET.fromstring(_svg_of(FILETYPE_SVG_DEFAULT))


def test_every_icon_escapes_the_characters_that_would_break_the_attribute():
    """``#`` truncates the URI; ``<``/``>`` end the src attribute early."""
    for ext, uri in sorted(FILETYPE_SVGS.items()):
        body = uri.split(",", 1)[1]
        for ch in ("#", "<", ">"):
            assert ch not in body, f"{ext}: raw {ch!r} in the data URI"


def test_no_icon_contains_a_double_quote():
    """Consumers write ``src="{uri}"``; a double quote inside would close it."""
    for ext, uri in sorted(FILETYPE_SVGS.items()):
        assert '"' not in uri, ext


def test_no_icon_uses_a_text_element():
    """The whole point of the rewrite.

    An SVG ``<text>`` with no ``font-family`` falls back to the engine's serif,
    and at the 16px these render at, a ``font-size='5'`` label in a 24-unit
    viewBox is 3.3 CSS pixels - unreadable, and differently unreadable per
    platform.
    """
    for ext, uri in sorted(FILETYPE_SVGS.items()):
        assert "<text" not in _svg_of(uri), ext
        assert "font-size" not in _svg_of(uri), ext


# --- The legibility floor ---------------------------------------------------

def test_no_stroke_is_thinner_than_its_device_pixel_floor():
    """Two floors, because the two kinds of stroke fail differently.

    A WHITE stroke IS the glyph - thin it and nothing is left - so it holds the
    full 1.7 units (1.13 CSS px at a 16px render, 2.3 device px at 2x). A stroke
    in the page colour is a CUT through a solid white shape, which carries the
    reading on its own, so a softened cut costs detail rather than the glyph;
    those get 1.5.

    Holding cuts to the outline floor is what made the link, markup and markdown
    marks collide with themselves, so the distinction is the fix, not a
    concession - but a cut still has a floor, or it disappears entirely.

    ONE EXEMPTION, and it is a different constraint rather than a softer one.
    The globe is made ENTIRELY of lines that enclose an area, so they must not
    close up the area they enclose - measured, a 1.7 stroke on its r=4.3 circle
    filled 81.7% of the disc and the glyph read as a blob. At r=5.0 a 1.4 stroke
    lands at 65% and the page shows through. Visibility is not at risk there: 1.4
    units is 1.87 device pixels at 16px on a 2x display, on a long continuous
    contour rather than an isolated tick.
    """
    import re

    exempt = {"webpage": 1.4}

    seen_cut = 0
    for name, glyph in sorted(_GLYPHS.items()):
        for stroke, width in re.findall(
            r"stroke='(#fff|\{c\})'\s+stroke-width='([\d.]+)'", glyph
        ):
            if stroke == "#fff":
                floor = exempt.get(name, 1.7)
            else:
                floor = 1.5
            assert float(width) >= floor, f"{name}: {stroke} stroke-width {width} < {floor}"
            seen_cut += stroke == "{c}"
    assert seen_cut, "the scan matched no cut strokes - the attribute order moved"
    assert set(exempt) <= set(_GLYPHS), "an exemption names a glyph that no longer exists"


def test_every_stroke_declares_a_width():
    """A stroke with no width silently renders at 1 user unit - .67 CSS px."""
    import re

    for name, glyph in sorted(_GLYPHS.items()):
        strokes = len(re.findall(r"stroke='(?:#fff|\{c\})'", glyph))
        widths = len(re.findall(r"stroke-width='", glyph))
        assert strokes == widths, f"{name}: {strokes} strokes but {widths} widths"


def test_every_absolutely_placed_shape_stays_inside_the_page():
    """The page is x 4..20, y 2..22, and the fold occupies y < 8 on the right.

    The old labels overflowed the sheet (``HTML`` and ``OTHER`` visibly touched
    its edges), so bounds are worth pinning - but only where they can be computed
    EXACTLY. ``<rect>`` and ``<circle>`` carry absolute geometry; path data holds
    relative deltas, so a max-over-the-literals test would be measuring nothing
    (it read ``rx='.95'`` as the coordinate 95). The path glyphs are checked
    visually instead, in scripts/filetype_icon_gallery.py, which renders the real
    icons at real size.

    Coordinates here are PRE-RISE: _ft_icon lifts every glyph by _GLYPH_RISE, so
    the shipped y is the declared y minus that constant. Checking the declared
    value would let a raised glyph drift off the top of the page unnoticed.
    """
    import re

    checked = 0
    for name, glyph in sorted(_GLYPHS.items()):
        for m in re.finditer(
            r"<rect x='([\d.]+)' y='([\d.]+)' width='([\d.]+)' height='([\d.]+)'", glyph
        ):
            x, y, w, h = (float(v) for v in m.groups())
            y -= _GLYPH_RISE
            assert 4.0 <= x and x + w <= 20.0, f"{name}: rect spans x {x}..{x + w}"
            assert 2.0 <= y and y + h <= 22.0, f"{name}: rect spans y {y}..{y + h}"
            checked += 1
        for m in re.finditer(r"<circle cx='([\d.]+)' cy='([\d.]+)' r='([\d.]+)'", glyph):
            cx, cy, r = (float(v) for v in m.groups())
            cy -= _GLYPH_RISE
            assert 4.0 <= cx - r and cx + r <= 20.0, f"{name}: circle spans x {cx - r}..{cx + r}"
            assert 2.0 <= cy - r and cy + r <= 22.0, f"{name}: circle spans y {cy - r}..{cy + r}"
            checked += 1
    assert checked >= 20, "the scan matched almost nothing - the shape syntax moved"


def test_every_family_clears_the_non_text_contrast_floor():
    """A white glyph on a light fill is not a glyph.

    WCAG 2.1 SC 1.4.11 puts non-text contrast at 3:1, and the ramp's first
    version was picked for hue alone and missed it on six of fourteen - zip at
    1.92 was barely a mark at all. This is the check that was absent, so it is
    the one that keeps a future hue change honest.
    """
    def _lum(h):
        h = h.lstrip("#")
        ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        ch = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

    def _ratio(a, b):
        la, lb = _lum(a), _lum(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    for colour, glyph, exts in _FAMILIES:
        assert _ratio("#ffffff", colour) >= 3.0, (
            f"{exts[0]} ({colour}): white glyph contrast "
            f"{_ratio('#ffffff', colour):.2f} < 3.0"
        )
        # Darkening for glyph contrast is spent against the app's own ground, so
        # the page must still separate from it. The unknown page is the floor
        # that has always shipped.
        assert _ratio(colour, "#0e1117") >= 2.5, (
            f"{exts[0]} ({colour}): lost against the app background"
        )


# --- The template -----------------------------------------------------------

def test_the_fold_tint_is_derived_from_the_page_colour():
    """One hex per family: a written-down tint is one that can drift from it."""
    assert _mix("#000000", 0.0) == "#000000"
    assert _mix("#000000", 1.0) == "#ffffff"
    assert _mix("#ef4444", 0.45) != "#ef4444"
    # The tint must actually be lighter than its page, or the fold disappears.
    r_page = int("ef", 16)
    r_fold = int(_mix("#ef4444", 0.45).lstrip("#")[0:2], 16)
    assert r_fold > r_page


def test_every_icon_shares_the_one_page_and_the_one_fold():
    """The rewrite's premise. 19 hand-copied pages is how HTML came to overflow
    its sheet while PDF did not."""
    from shared.filetype_icons import _PAGE

    page_d = _PAGE.split("d='")[1].split("'")[0]
    for ext, uri in sorted(FILETYPE_SVGS.items()):
        assert page_d in _svg_of(uri), ext


def test_families_are_distinguished_by_colour_not_only_by_glyph():
    """pdf/doc/txt deliberately share the 'lines' glyph - colour is what
    separates them, and that is the convention users already read. So the three
    must not collapse onto one icon."""
    assert FILETYPE_SVGS["pdf"] != FILETYPE_SVGS["doc"] != FILETYPE_SVGS["txt"]
    assert FILETYPE_SVGS["pdf"] != FILETYPE_SVGS["txt"]


def test_an_unknown_glyph_name_fails_loudly():
    with pytest.raises(KeyError):
        _ft_icon("#ffffff", "no-such-glyph")
