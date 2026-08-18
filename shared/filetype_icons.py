"""shared.filetype_icons - the one filetype icon set.

WHAT REPLACED WHAT, AND WHY
---------------------------
These used to be 19 hand-written ``data:`` URIs, each a copy of the same page
path with two fills swapped and a ``<text>`` label dropped on top. Three things
were wrong with that, and all three are structural rather than taste:

* **The label was unreadable at the size it ships.** ``font-size='5'`` in a 24
  unit viewBox rendered at 16px is **3.3 CSS pixels**. Every icon was a coloured
  rectangle with a smudge on it; the label contributed nothing.
* **The label rendered in the engine's default serif.** No ``font-family`` was
  set, and an SVG ``<text>`` then falls back to Times - a serif badge inside a
  system-sans UI, whose glyph metrics differ between WebView2 and WKWebView. The
  per-icon ``x=`` offsets (7 for PDF, 4 for HTML, 2 for OTHER) were hand-tuned to
  fake centring against ONE engine's metrics, and ``HTML``/``OTHER`` overflowed
  the page shape anyway.
* **The corner was not a fold.** The body path already covered that corner, so
  the lighter triangle just sat flush on top of it.

So the extension is now carried by a **glyph**, and the family by **colour** -
the two signals that survive 16px. No information is lost, because every surface
that renders one of these already prints an ``EXT`` badge beside it
(``li-ext-badge``, ``skip-ext-badge``, the pill's ``ft-label``). The icon says
"spreadsheet, Excel-green"; the badge next to it says "XLSM".

**Recognition is carried by colour first.** Red is a PDF, blue is a document,
green is a spreadsheet, orange is a deck - that is what a user reads at 16px, and
it is the convention every file manager they already use follows. The glyph
disambiguates within a colour and reinforces across one. This is deliberately the
Google Drive model, whose Docs icon is a blue page with white lines and whose PDF
is a red page with white lines: identical glyphs under different colours are not
a missed opportunity, they are the statement "both of these are text documents".

BUILT FROM ONE TEMPLATE, NOT COPIED
-----------------------------------
``_ft_icon()`` assembles every icon from ONE page silhouette, ONE fold and a
named glyph, so a new type is one entry in ``_FAMILIES`` rather than a 400-byte
string nobody will proofread. Same reason this app has one ``make_long_path`` and
one ``applescript_string``: a rule written 19 times is a rule some of the copies
are an old version of - which is exactly how ``HTML`` came to overflow its page
while ``PDF`` did not.

**The fold tint is DERIVED, never chosen** (``_mix`` toward white), so it cannot
drift from the page it belongs to and a family costs exactly one hex.

**Coverage is the other half of the defect.** The old table had 18 keys, and 10
of the 26 extensions its own pill whitelist named had no icon at all (``c cpp css
java js json md py sql webloc``) - those rendered as a blank grey page beside a
label reading "PY". So did ``.md`` and ``.srt``, which are outputs this app
PRODUCES (the html->md converter; Panopto subtitles, hit directly in the Confirm
Sync dialog at ui/sync_confirmation.py), and ``.pptm``/``.pot``/``.potx``, which
even the *most restrictive* file filter admits.
``tests/test_filetype_icons.py`` reads the engine's own extension sources and
fails when one of them grows past this table, so coverage cannot fall behind
again.
"""

from __future__ import annotations

# --- Palette ---------------------------------------------------------------
# A filetype ramp: one hex per FAMILY, spaced around the hue wheel so that no two
# families a user must tell apart sit next to each other. Three are app tokens
# already; the rest have no token because no other surface in this app is a
# saturated file-manager colour, and minting twelve one-use names in
# shared/theme.py would make the palette harder to reason about, not easier.
# audit-ignore: a deliberate ramp, documented here - see the "Colours: pick from
# a ramp" rule. Every member is more than 1.0 CIEDE2000 from every token AND from
# every other member, which is the property that keeps them apart at 16px.
#
# EVERY MEMBER CARRIES A WHITE GLYPH, SO EVERY MEMBER OWES IT 3:1.
# That is WCAG's non-text contrast floor, and the first version of this ramp was
# picked for hue alone and missed it on six of fourteen - measured white-on-fill:
# zip 1.92, url 2.14, xls 2.28, html 2.43, jpg 2.49, ppt 2.80. On the light ones
# the glyph was barely separable from the page it sat on. Each was walked down
# its own hue ramp to the first step that clears 3:1 while staying recognisably
# the same colour, which cost two token alignments (ACCENT_LINK, PHASE_PROCESS)
# and is worth it. Archive stops at the FIRST step that clears rather than the
# safest one on purpose: yellow is intrinsically light, so every step darker than
# this reads as brown, and a brown archive is a different colour rather than the
# same colour with more contrast. It clears at 3.19 and stays 11.6 CIEDE2000 from
# the deck orange it must not be confused with. The second number is contrast against the app's #0e1117
# ground, which darkening spends - none of these drops below 3.8, against 2.50
# for the unknown page that has always shipped.
#                                white/fill   on #0e1117
C_RED     = "#ef4444"   # pdf          3.76        5.02   = theme.ERROR
C_ORANGE  = "#ea580c"   # decks        3.56        5.31
C_AMBER   = "#d97706"   # archives     3.19        5.93
C_GREEN   = "#16a34a"   # spreadsheets 3.30        5.73
C_TEAL    = "#0d9488"   # images       3.74        5.05
C_CYAN    = "#0891b2"   # the web      3.68        5.13
C_SKY     = "#0284c7"   # links        4.10        4.61
C_BLUE    = "#3b82f6"   # documents    3.68        5.14   = theme.BLUE_PRIMARY
C_INDIGO  = "#6366f1"   # source code  4.47        4.23
C_PURPLE  = "#a855f7"   # audio        3.96        4.78
C_PINK    = "#ec4899"   # video        3.53        5.36
C_SLATE   = "#64748b"   # subtitles    4.76        3.97
C_GRAY    = "#6b7280"   # plain text   4.83        3.91   = theme.TEXT_GRAY_500
C_UNKNOWN = "#4b5563"   # unnamed      7.56        2.50


def _mix(hex_colour: str, amount: float) -> str:
    """*hex_colour* blended *amount* of the way toward white."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))

    def f(c: int) -> int:
        return round(c + (255 - c) * amount)

    return "#{:02x}{:02x}{:02x}".format(f(r), f(g), f(b))


# --- Geometry --------------------------------------------------------------
# The page: x 4..20, y 2..22, corner radius 2, with the top-right corner CUT away
# from (14,2) to (20,8). The cut is what makes it read as a sheet of paper; the
# old icons filled that corner and laid a lighter triangle over it, which is why
# their "fold" looked flat.
_PAGE = "<path d='M6 2h8l6 6v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z' fill='{c}'/>"
# The fold fills exactly that cut, wound in the same direction as the body's
# diagonal so the two share an edge rather than overlapping on it.
_FOLD = "<path d='M14 2v4.5a1.5 1.5 0 0 0 1.5 1.5H20z' fill='{t}'/>"

# THE FRAME A GLYPH IS CENTRED IN IS THE FOLD'S SQUARE, NOT THE WHOLE PAGE.
# The fold's lower edge at y=8 cuts the sheet into a top strip and a square below
# it (y 8..22, x 4..20), and that square is what the eye reads as the icon's body.
# Glyphs were laid out to sit in "the page's lower two thirds", which put their
# ink around y=15.3 - low in that square, leaving barely more than a sliver of
# solid colour under them. It is worst exactly where it is least affordable: at
# 16px the whole page is under 11 CSS pixels tall, so a 2.4-unit foot is 1.6px.
#
# Every glyph is therefore lifted by ONE constant applied in _ft_icon, rather
# than by editing thirteen coordinate sets - the same reason the page and the
# fold are written once. Raising it moves the whole set together and can never
# leave one glyph behind.
_GLYPH_RISE = 0.7

# --- Glyphs ----------------------------------------------------------------
# Each occupies roughly x 6.5..17.5, y 11..19.7 - the page's lower two thirds,
# which is as large as a mark can be while leaving the fold legible.
#
# TWO STROKE FLOORS, because the two kinds of stroke fail differently.
# A WHITE stroke IS the glyph: if it thins out there is nothing left, so it never
# goes below 1.7 units - 1.13 CSS px at a 16px render, i.e. 2.3 device pixels on a
# 2x display. A stroke in ``{c}``, the page colour, is a CUT through a solid white
# shape, and the shape carries the reading on its own; a cut that softens at 16px
# costs detail, not the glyph. Those may go to 1.5. Keeping one floor for both
# forced every cut to be as heavy as an outline, which is what made the link,
# markup and markdown marks collide with themselves.
_GLYPHS = {
    # Lines of text. Carries pdf / word / plain text; the colour says which.
    "lines": (
        "<rect x='6.9' y='11.1' width='10.2' height='1.9' rx='.95' fill='#fff'/>"
        "<rect x='6.9' y='14.4' width='10.2' height='1.9' rx='.95' fill='#fff'/>"
        "<rect x='6.9' y='17.7' width='6.6' height='1.9' rx='.95' fill='#fff'/>"
    ),
    # A table: header band over a 2x2 body. Reads as a spreadsheet at 16px, where
    # a drawn grid of thin rules turns to mush.
    "grid": (
        "<rect x='6.9' y='11.1' width='10.2' height='2.3' rx='.8' fill='#fff'/>"
        "<rect x='6.9' y='14.6' width='4.5' height='2.2' rx='.7' fill='#fff'/>"
        "<rect x='12.6' y='14.6' width='4.5' height='2.2' rx='.7' fill='#fff'/>"
        "<rect x='6.9' y='17.5' width='4.5' height='2.2' rx='.7' fill='#fff'/>"
        "<rect x='12.6' y='17.5' width='4.5' height='2.2' rx='.7' fill='#fff'/>"
    ),
    # A slide carrying a bar chart. The bars are the PAGE colour cut back out of
    # a white slide, which is far more legible at 16px than white-on-colour
    # detail inside an outlined frame.
    "slide": (
        "<rect x='6.7' y='11' width='10.6' height='8.6' rx='1.3' fill='#fff'/>"
        "<rect x='8.5' y='15.2' width='1.9' height='2.7' rx='.6' fill='{c}'/>"
        "<rect x='11.05' y='13.3' width='1.9' height='4.6' rx='.6' fill='{c}'/>"
        "<rect x='13.6' y='14.4' width='1.9' height='3.5' rx='.6' fill='{c}'/>"
    ),
    # Sun over a ridge - the universal picture mark. Drawn without a frame: the
    # page already is the frame, and a frame plus its contents is two nested
    # shapes inside 7 CSS pixels.
    "image": (
        "<circle cx='9.2' cy='12.7' r='1.6' fill='#fff'/>"
        "<path d='M6.9 19.6l3.6-4.4 2.3 2.8 2.1-2.5 3.1 4.1z' fill='#fff'/>"
    ),
    # A play triangle, CENTRED. The first version was built from a rounded path
    # whose arc bulged past its own control points, so it sat 1.35 units right of
    # centre - its left edge landed two fifths across the page. Corners are
    # rounded by stroking the triangle in its own fill with a round join, which
    # is exact: the outline grows by half the stroke on every side, so the shape
    # stays centred instead of being nudged by hand. Verified by rasterising the
    # icon and measuring the white ink against the page: 0.13 units off centre,
    # against 0.00 for every glyph built from rects. The remaining hair of right
    # bias is correct - a right-pointing triangle carries its mass on the base,
    # so its centroid sits left of its bounding box.
    "video": (
        "<path d='M9 11.9L15.3 15.3 9 18.7z' fill='#fff' stroke='#fff'"
        " stroke-width='1.7' stroke-linejoin='round'/>"
    ),
    # Two beamed quavers, drawn as ONE closed outline for the beam and stems with
    # a circle at each stem's foot. The first version stroked the stems as a
    # polyline and dropped circles on the ends: a round CAP is half the stroke
    # wide while the notehead is 1.75, so the stem overshot the head on one side
    # and left an unfilled notch on the other. Here each stem's right edge is the
    # notehead's right edge and its foot is the notehead's centre, so the two
    # overlap by a full radius and fuse with no seam to fill.
    "audio": (
        "<path d='M9.3 18.25V11.25L16.5 10.05V17.15H14.9V12.22L10.9 12.88V18.25z'"
        " fill='#fff'/>"
        "<circle cx='9.15' cy='18.25' r='1.75' fill='#fff'/>"
        "<circle cx='14.75' cy='17.15' r='1.75' fill='#fff'/>"
    ),
    # A zipper: teeth alternating across the seam, above a wide pull with a slot.
    # Both halves are shaped against the same misread - a NARROW column sitting
    # on a TALL rounded body is a padlock, which is what the first two drafts
    # looked like at 64px. Offsetting the teeth breaks the straight shackle line,
    # and a pull wider than it is tall with a horizontal slot cannot be a lock
    # body. The zipper is the convention worth getting right: it is what both
    # Windows and macOS put on a .zip.
    "archive": (
        # TWO SPACINGS AND ONE CORNER. The teeth read as a track only if the gap
        # to the pull is clearly larger than the gap between them: at 0.2 against
        # 0.25 the whole thing was one clump, so the pull now sits 1.2 below the
        # last tooth - six times the tooth spacing.
        #
        # The corners were the other half, and this glyph was the set's outlier in
        # BOTH directions. Every other small bar here is a full pill (lines, code,
        # the subtitle captions, the unknown rules all sit at 1.00 of half-height)
        # and every other tile sits at 0.30-0.47; the teeth were at 0.54 and the
        # pull at 0.65, converging on each other from opposite sides, which is
        # precisely why they looked like parts of two different icons. Teeth are
        # pills now and the pull is squarer, which lands their ABSOLUTE radii at
        # .95 and 1.1 - close enough that the corners read as one curvature.
        "<rect x='8.8' y='9.1' width='3' height='1.9' rx='.95' fill='#fff'/>"
        "<rect x='12.2' y='11.2' width='3' height='1.9' rx='.95' fill='#fff'/>"
        "<rect x='8.8' y='13.3' width='3' height='1.9' rx='.95' fill='#fff'/>"
        "<rect x='8.6' y='16.4' width='6.8' height='3.9' rx='1.1' fill='#fff'/>"
        "<rect x='10.85' y='17.6' width='2.3' height='1.5' rx='.75' fill='{c}'/>"
    ),
    # An arrow to somewhere else, cut out of a solid tile. The first two versions
    # drew an OUTLINED frame with the arrow crossing its top-right corner, and at
    # a stroke heavy enough to survive 16px the two shapes collided. Recast in the
    # language the rest of the set already uses - a solid white shape with the
    # mark subtracted from it - which is also why the stroke can come back down:
    # a cut does not have to carry the glyph on its own, the tile does.
    # The arrow's INK is centred on the tile, which the first version was not: an
    # arrow is an L-head plus a diagonal, and the head only occupies the top-right
    # of the shape, so matching the two shapes' declared coordinates left the ink
    # a full unit high and a quarter right. The numbers below are chosen so that
    # ink spans 8.75..15.25 and 12.05..18.55 - centred on the tile's own
    # (12, 15.3) once the stroke's half-width is counted on every side.
    "link": (
        "<rect x='6.4' y='10.8' width='11.2' height='9' rx='2.1' fill='#fff'/>"
        "<path d='M9.6 17.7l4.8-4.8M11.6 12.9h2.8v2.8' fill='none' stroke='{c}'"
        " stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'/>"
    ),
    # A globe. It was </> until the obvious was pointed out: nearly every .html in
    # a course folder is a Canvas page the app EXPORTED - an assignment, a quiz, a
    # discussion - and the user opens it in a browser. A source-code mark
    # described how the file is written rather than what it is for.
    #
    # DRAWN, not subtracted, and it is THE EXCEPTION TO THE STROKE FLOOR.
    # A first version filled a white disc and cut the meridians out of it in the
    # page colour, which is not a globe - it is a disc with tan lines across it,
    # and what read as the globe was the leftover white rather than the lines.
    # A globe is its lines.
    #
    # Drawing it in white at the 1.7 outline floor did not fix it either: measured
    # by rasterising the icon and counting white pixels inside the disc, the lines
    # covered **81.7%** of their own circle - at r=4.3 a 1.7 stroke is 40% of the
    # radius, so three overlapping contours merge straight back into a blob. This
    # glyph carries a constraint no other one has: it is made ENTIRELY of lines
    # that enclose an area, so they must not close up the area they enclose, and
    # that binds tighter than visibility. Swept r/stroke and measured each: r=5.0
    # with a 1.4 stroke lands at 65% white, which is where the page reads clearly
    # through the gaps. 1.4 units is still 1.87 device pixels at 16px on a 2x
    # display, and this is a long continuous contour rather than a short tick, so
    # it survives where an isolated 1.4 stroke would not.
    # tests/test_filetype_icons.py names this glyph as the one exemption.
    "webpage": (
        "<circle cx='12' cy='15' r='5' fill='none' stroke='#fff' stroke-width='1.4'/>"
        "<path d='M7 15h10' fill='none' stroke='#fff' stroke-width='1.4'/>"
        "<ellipse cx='12' cy='15' rx='2.3' ry='5' fill='none' stroke='#fff'"
        " stroke-width='1.4'/>"
    ),
    # >_ - a shell prompt. Source code, and unmistakably not markup.
    "code": (
        "<path d='M7.3 12.1l3.3 3.3-3.3 3.3' fill='none' stroke='#fff'"
        " stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/>"
        "<rect x='12' y='17.5' width='5.5' height='2' rx='1' fill='#fff'/>"
    ),
    # The Markdown mark: an M and a descending arrow inside a rounded badge -
    # which is what the real logo is, so putting the badge back is both more
    # faithful and what fixes it. Drawn white, the M and the arrow were two
    # heavy strokes with nothing holding them together and they collided; cut out
    # of a tile they have a frame to sit in, and the tile is what reads at 16px.
    "markdown": (
        "<rect x='6.5' y='11.4' width='11' height='7.8' rx='1.7' fill='#fff'/>"
        # The M and the arrow must not touch. At a 1.5 stroke each shape's ink runs
        # .75 past its coordinates, so the previous M (to 12.0) and arrow (from
        # 12.5) overlapped by a quarter unit and read as one joined mark. The M is
        # narrower and the arrow sits further right, leaving a full unit of page
        # between their ink; the pair still centres on 12.
        "<path d='M8 17.2v-3.8l1.6 2 1.6-2v3.8' fill='none' stroke='{c}'"
        " stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/>"
        "<path d='M14.85 13.3v2.9M13.75 15.6l1.1 1.6 1.1-1.6' fill='none' stroke='{c}'"
        " stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/>"
    ),
    # A screen with caption bars along its foot, cut back out of a solid white
    # block - the same technique as the deck, and for the same reason: an
    # OUTLINED screen holding two small bars is three thin shapes inside 7 CSS
    # pixels, and it collapsed into a grey smudge at 16px. It cannot be confused
    # with the deck despite the shared construction: those bars are vertical and
    # central, these are horizontal and sit on the floor, and the colours are a
    # hue wheel apart.
    "subtitles": (
        "<rect x='6.7' y='11.2' width='10.6' height='8.3' rx='1.4' fill='#fff'/>"
        "<rect x='8.6' y='16.1' width='3.4' height='1.7' rx='.85' fill='{c}'/>"
        "<rect x='13' y='16.1' width='2.6' height='1.7' rx='.85' fill='{c}'/>"
    ),
    # Deliberately faint, and only two lines: it must read as "a file" without
    # claiming to know which kind. The old default carried no mark at all, so an
    # unrecognised type was a blank grey page.
    "unknown": (
        "<rect x='7.2' y='12.7' width='9.6' height='1.8' rx='.9' fill='#fff' opacity='.5'/>"
        "<rect x='7.2' y='16.1' width='6.2' height='1.8' rx='.9' fill='#fff' opacity='.5'/>"
    ),
}


def _ft_icon(colour: str, glyph: str) -> str:
    """One page + one fold + *glyph*, as the ``data:`` URI an ``<img>`` takes.

    ``#`` MUST be escaped or the URI truncates at the first colour, and
    ``<``/``>`` MUST be escaped or the markup ends the attribute early. Quoting
    inside the SVG is single throughout, so every consumer's ``src`` attribute
    has to be double-quoted - the rule already written beside the call sites.
    """
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
        + _PAGE.format(c=colour)
        + _FOLD.format(t=_mix(colour, 0.45))
        + f"<g transform='translate(0 -{_GLYPH_RISE})'>"
        + _GLYPHS[glyph].format(c=colour)
        + "</g></svg>"
    )
    return "data:image/svg+xml," + (
        svg.replace("%", "%25").replace("#", "%23").replace("<", "%3C").replace(">", "%3E")
    )


# --- Families --------------------------------------------------------------
# (colour, glyph, extensions). The extension lists are a superset of everything
# the app can produce or admit: STUDY_FILE_EXTENSIONS, both sides of
# _EFFECTIVE_EXT_MAP, converters.code.CODE_EXTENSIONS, the Panopto output kinds
# and both shortcut extensions. tests/test_filetype_icons.py reads those sources
# directly, so this table cannot silently fall behind them.
_FAMILIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (C_RED,     "lines",     ("pdf",)),
    (C_BLUE,    "lines",     ("doc", "docx", "docm", "dot", "dotx", "rtf", "odt",
                              "pages", "wpd")),
    (C_GREEN,   "grid",      ("xls", "xlsx", "xlsm", "xlsb", "xlt", "xltx", "ods",
                              "numbers", "csv", "tsv")),
    (C_ORANGE,  "slide",     ("ppt", "pptx", "pptm", "pps", "ppsx", "pot", "potx",
                              "odp", "key")),
    (C_TEAL,    "image",     ("jpg", "jpeg", "jpe", "png", "gif", "bmp", "webp",
                              "tif", "tiff", "heic", "heif", "svg", "ico", "avif",
                              "psd")),
    (C_PINK,    "video",     ("mp4", "m4v", "mov", "mkv", "avi", "webm", "wmv",
                              "flv", "mpg", "mpeg", "mts", "3gp")),
    (C_PURPLE,  "audio",     ("mp3", "wav", "m4a", "aac", "flac", "ogg", "oga",
                              "wma", "aiff", "aif", "opus")),
    (C_AMBER,   "archive",   ("zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz",
                              "iso")),
    (C_SKY,     "link",      ("url", "webloc", "lnk", "desktop")),
    (C_CYAN,    "webpage",   ("html", "htm", "xhtml", "xml")),
    (C_CYAN,    "markdown",  ("md", "mdx", "markdown", "rst")),
    (C_SLATE,   "subtitles", ("srt", "vtt", "sub", "ass", "sbv")),
    (C_GRAY,    "lines",     ("txt", "text", "log", "nfo", "readme")),
    (C_INDIGO,  "code",      ("py", "pyw", "ipynb", "js", "jsx", "mjs", "cjs",
                              "ts", "tsx", "java", "class", "jar", "c", "h", "cpp",
                              "hpp", "cc", "cs", "go", "rs", "rb", "php", "swift",
                              "kt", "kts", "scala", "sh", "bash", "zsh", "bat",
                              "cmd", "ps1", "pl", "pm", "r", "rmd", "m", "mm",
                              "sql", "dart", "lua", "asm", "vba", "vb", "css",
                              "scss", "sass", "less", "json", "jsonc", "yaml",
                              "yml", "toml", "ini", "cfg", "conf", "env", "vue",
                              "svelte", "gradle", "make", "dockerfile")),
    # 'other' is the aggregate bucket the filetype pills roll rare types into. It
    # shares the unknown icon on purpose: both mean "not named here".
    (C_UNKNOWN, "unknown",   ("other",)),
)

FILETYPE_SVGS: dict[str, str] = {}
for _colour, _glyph, _exts in _FAMILIES:
    _uri = _ft_icon(_colour, _glyph)
    for _ext in _exts:
        FILETYPE_SVGS[_ext] = _uri

FILETYPE_SVG_DEFAULT: str = _ft_icon(C_UNKNOWN, "unknown")
