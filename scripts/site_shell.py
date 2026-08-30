"""The site's shared page shell, lifted from ``docs/win-setup.html``.

This exists for the two DATA pages only - ``canvas-url-directory.html`` and
``canvas-data.html`` - whose bodies are 4,757 rows generated from
``shared/institutions.py``. Those are tables, not writing, so they are built.

Everything else under ``docs/`` is hand-maintained. There used to be a
``build_guide_pages.py`` that rebuilt the thirteen articles and ``blog.html``
from a Python file on every run; it was deleted 2026-08-31 because an article
is a document, not a build artifact, and re-running it silently reverted
hand-edits made to the pages in between. Do not reintroduce that pattern. If
the nav changes, edit the pages.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
SITE = "https://canvasdownloader.app/"
OG = SITE + "assets/og-card.png"
OG_ALT = ("Canvas Downloader - download every file from all your Canvas courses "
          "at once")


def _shell() -> tuple[str, str, str, str]:
    """CSS, nav, footer and trailing script, lifted from win-setup.html."""
    src = (DOCS / "win-setup.html").read_text(encoding="utf-8")
    css = src[src.index("<style>"): src.index("</style>") + len("</style>")]
    nav = src[src.index("  <!-- NAV -->"): src.index("</nav>") + len("</nav>")]
    # win-setup.html marks "How to set up" as the current page. Lifting its nav
    # verbatim told every visitor to a data page that they were on the setup
    # page - the cyan highlight is the only "you are here" signal the nav has.
    # A data page is not any of the nav's four destinations, so none is active.
    nav = nav.replace('class="nav-link active"', 'class="nav-link"')
    foot = src[src.index("  <footer>"): src.index("</footer>") + len("</footer>")]
    tail = src[src.index("  <script>"): src.index("</body>")]
    return css, nav, foot, tail
