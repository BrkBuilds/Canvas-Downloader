"""build_store_page.py - render the Store submission working page from STORE_LISTING.md.

WHY THIS IS GENERATED AND NOT HAND-WRITTEN
------------------------------------------
The page exists to be *copied out of* while somebody works through Partner
Center, so every block on it has to be byte-identical to what the repo says the
listing should contain. A hand-maintained HTML copy of that text is the same
defect this project has hit repeatedly under other names - one rule written
twice, and the second copy silently going stale. ``marketing/STORE_LISTING.md``
is the single source; this script is the only thing allowed to restate it.

It emits TWO files, and both are needed for different reasons:

* ``store-listing.artifact.html`` - **no** doctype/html/head/body. The Artifact
  tool supplies that skeleton at publish time, so a source file carrying its own
  would nest one document inside another.
* ``store-listing.html`` - the same page wrapped as a complete document.
  Opening the artifact source directly with ``file://`` puts the browser in
  QUIRKS MODE, which is a different box model, so the layout reviewed in the
  artifact is not the layout that appears on disk. This is the copy to hand over.

Run:  python marketing/build_store_page.py
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "STORE_LISTING.md"
TEMPLATE = HERE / "store_page_template.html"
OUT_ARTIFACT = HERE / "store-listing.artifact.html"
OUT_STANDALONE = HERE / "store-listing.html"

#: Each pasteable field, keyed by the template token, found by the first line of
#: its fenced block. Matching on the opening TEXT rather than on block order is
#: deliberate: a new section inserted into the markdown must not silently shift
#: every field by one.
FIELDS = {
    "SHORT": "Get all your Canvas course files onto your computer",
    "DESC": "Canvas Downloader downloads all your Canvas course files",
    "WHATSNEW": "This is a big jump from the version on the Store.",
    "FEATURES": "Download every Canvas course in one run",
    "KEYWORDS": "canvas course downloader",
    "LICENCE": "https://github.com/BrkBuilds/Canvas-Downloader",
    "COPYRIGHT": "(c) BrkBuilds. Licensed under GPL-3.0-or-later.",
    "OLD_PRIVACY": None,   # pulled out of the 404 table instead
    "OLD_SITE": None,
    "OLD_SUPPORT": None,
}

#: Slot 4 is Panopto, which the page tints purple to mark the deliberate reorder.
PURPLE_SLOT = 4


def fenced_blocks(md: str) -> list[str]:
    """Every ``` fenced block in the document, in order, undecorated."""
    return [b.strip("\n") for b in re.findall(r"^```[a-z]*\n(.*?)^```", md, re.S | re.M)]


def pick(blocks: list[str], prefix: str, token: str) -> str:
    hits = [b for b in blocks if b.startswith(prefix)]
    if len(hits) != 1:
        sys.exit(
            f"[store-page] {token}: expected exactly one fenced block starting "
            f"{prefix!r}, found {len(hits)}. STORE_LISTING.md changed shape - "
            f"fix the anchor rather than loosening the match."
        )
    return hits[0]


def dead_links(md: str) -> dict[str, str]:
    """The three old URLs, read out of the 404 evidence table."""
    out = {}
    for token, label in (("OLD_PRIVACY", "Privacy policy"),
                         ("OLD_SITE", "App website"),
                         ("OLD_SUPPORT", "Support")):
        m = re.search(r"^\| " + re.escape(label) + r" \| `([^`]+)` \|", md, re.M)
        if not m:
            sys.exit(f"[store-page] could not find the {label!r} row of the 404 table.")
        out[token] = m.group(1)
    return out


def slots(md: str) -> str:
    """Build the carousel strip from the order table plus the captions block."""
    rows = re.findall(
        r"^\| (\d) \| `(CD_MSStore_[^`]+)` \| ([^|]+?) \|$", md, re.M)
    if len(rows) != 8:
        sys.exit(f"[store-page] expected 8 screenshot rows, found {len(rows)}.")

    caps_block = next((b for b in fenced_blocks(md) if b.startswith("1  Tick your courses")), None)
    if caps_block is None:
        sys.exit("[store-page] captions block not found.")
    caps = {}
    for line in caps_block.split("\n"):
        m = re.match(r"^(\d)\s\s+(.*)$", line)
        if m:
            caps[m.group(1)] = m.group(2).strip()
    if len(caps) != 8:
        sys.exit(f"[store-page] expected 8 captions, parsed {len(caps)}.")

    parts = []
    for num, fname, why in rows:
        cls = "slot pan" if int(num) == PURPLE_SLOT else "slot"
        parts.append(
            f'<div class="{cls}">'
            f'<span class="n">{html.escape(num)}</span>'
            f'<div>'
            f'<span class="file">{html.escape(fname)}</span>'
            f'<p class="why">{html.escape(why.strip())}</p>'
            f'<p class="cap"><em>Caption</em>{html.escape(caps[num])}</p>'
            f'</div></div>'
        )
    return "\n    ".join(parts)


WRAPPER_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{title}
</head>
<body>
"""


def main() -> int:
    md = SOURCE.read_text(encoding="utf-8")
    tpl = TEMPLATE.read_text(encoding="utf-8")
    blocks = fenced_blocks(md)

    values = {t: pick(blocks, p, t) for t, p in FIELDS.items() if p is not None}
    values.update(dead_links(md))

    page = tpl
    for token, text in values.items():
        marker = "{{" + token + "}}"
        if marker not in page:
            sys.exit(f"[store-page] template has no {marker} placeholder.")
        page = page.replace(marker, html.escape(text))
    page = page.replace("{{SLOTS}}", slots(md))

    leftover = re.findall(r"\{\{[A-Z_]+\}\}", page)
    if leftover:
        sys.exit(f"[store-page] unfilled placeholders: {sorted(set(leftover))}")

    OUT_ARTIFACT.write_text(page, encoding="utf-8", newline="\n")

    # The standalone copy: lift <title> and the two font <link>s into a real
    # <head>, so the file opens in standards mode from disk.
    body = page
    head_bits = []
    for pattern in (r"<title>.*?</title>", r'<link rel="preconnect"[^>]*>',
                    r'<link rel="stylesheet" href="https://fonts\.googleapis[^>]*>'):
        for m in re.findall(pattern, body):
            head_bits.append(m)
            body = body.replace(m, "", 1)
    standalone = (WRAPPER_HEAD.format(title="\n".join(head_bits))
                  + body.lstrip("\n") + "\n</body>\n</html>\n")
    OUT_STANDALONE.write_text(standalone, encoding="utf-8", newline="\n")

    assert standalone.lstrip().startswith("<!doctype html>")
    external = [u for u in re.findall(r'https?://[^"\')\s]+', standalone)
                if "fonts.googleapis.com" not in u and "fonts.gstatic.com" not in u]
    remote_assets = [u for u in external
                     if re.search(r"\.(png|jpe?g|gif|svg|webp|js|css|woff2?)$", u)]

    print(f"[store-page] {len(values)} copy blocks + 8 slots rendered from STORE_LISTING.md")
    print(f"[store-page] artifact source -> {OUT_ARTIFACT.name}")
    print(f"[store-page] standalone      -> {OUT_STANDALONE.name}  ({len(standalone):,} bytes)")
    print(f"[store-page] remote asset references (must be 0): {len(remote_assets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
