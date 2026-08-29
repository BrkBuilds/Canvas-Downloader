"""Build the two search-facing guide pages from the site's own shell.

WHY THIS SCRIPT EXISTS
----------------------
Every page under ``docs/`` inlines its own copy of the nav, the footer and a
~6.5 KB stylesheet. That is fine for six hand-written pages and a liability for
pages that are meant to keep being added: a new page written by hand drifts from
the others the first time the nav changes, and the drift is invisible until
somebody looks at two pages side by side.

So these pages are COMPOSED from ``docs/win-setup.html`` - the smallest page on
the site - which is the source of truth for the shell. Change the nav there and
re-run this script; the guide pages follow.

WHAT THESE PAGES ARE FOR
------------------------
Every existing page documents the PRODUCT. Nothing on the site answers the
question a student actually types into Google. Measured 2026-08-20: for "how to
download all files from Canvas at once" the results are university help desks
(Stanford, Illinois, Clemson, Pitt, NCTC, UNT) and an Instructure Community
thread, and all of them stop at the same place - Canvas can zip ONE course's
Files tab, and nothing covers Pages, Assignments or multiple courses. The
accepted answer in that community thread says so in as many words: "As for Pages
and Assignments, I'm not sure of a quick way off the top of my head."

That gap is the opportunity, and it is only an opportunity if the page is
genuinely the most useful answer on the subject. So both pages lead with what
Canvas can do by itself, describe the alternatives fairly including the ones
that compete with this app, and mention the product where it is the honest
answer and not before.

VOCABULARY RULE
---------------
Students say "Canvas". They do not say "LMS" - it is administrator vocabulary
and it reads as noise to the person this page is for. "Canvas LMS" appears only
inside JSON-LD, where it disambiguates for machines and no student reads it.

Run:  python scripts/build_guide_pages.py
"""
from __future__ import annotations

import datetime
import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
SITE = "https://canvasdownloader.app/"
OG = SITE + "assets/og-card.png"
OG_ALT = ("Canvas Downloader - download every file from all your Canvas courses "
          "at once")

# ---------------------------------------------------------------- shell -----

def _shell() -> tuple[str, str, str, str]:
    """CSS, nav, footer and trailing script, lifted from win-setup.html."""
    src = (DOCS / "win-setup.html").read_text(encoding="utf-8")
    css = src[src.index("<style>"): src.index("</style>") + len("</style>")]
    nav = src[src.index("  <!-- NAV -->"): src.index("</nav>") + len("</nav>")]
    # win-setup.html marks "How to set up" as the current page. Lifting its nav
    # verbatim told every visitor to a guide page that they were on the setup
    # page - the cyan highlight is the only "you are here" signal the nav has.
    # A guide page is not any of the nav's four destinations, so none is active.
    nav = nav.replace('class="nav-link active"', 'class="nav-link"')
    foot = src[src.index("  <footer>"): src.index("</footer>") + len("</footer>")]
    tail = src[src.index("  <script>"): src.index("</body>")]
    return css, nav, foot, tail


# Extra rules for long-form prose. The shell's stylesheet is written for short
# setup pages, so it has no article typography at all.
ARTICLE_CSS = """
    /* ---- ARTICLE (guide pages) ---- */
    /* width: 100% is load-bearing, not tidying, and it is the ONLY thing that
       fixes this - min-width: 0 was tried first and measured no different.

       The shell makes <body> a COLUMN FLEX container, so .container is a flex
       item and its width is the CROSS size. With width:auto that size is
       resolved from content, and the comparison table declares min-width:640px,
       so on a 390px phone the container came out 688px wide and the WHOLE PAGE
       scrolled sideways (measured: 172 elements past the viewport edge).
       A definite width stops the content-based sizing, the container lands at
       342px, and .tbl-wrap's own overflow-x then does its job: the table scrolls
       inside its box and the page does not. Verified at 390 / 768 / 1180. */
    .container.wide { max-width: 800px; width: 100%; }
    .art { text-align: left; padding-bottom: 20px; }
    /* The shell h1 inherits body line-height 1.6, which is right for a
       one-line setup title and far too airy for a two-line article title. */
    .hero h1 { line-height: 1.12; }
    .art h2 {
      font-size: clamp(21px, 3vw, 27px);
      font-weight: 800;
      letter-spacing: -0.02em;
      margin: 46px 0 14px;
      scroll-margin-top: 80px;
    }
    .art h3 { font-size: 17px; font-weight: 700; margin: 28px 0 8px; }
    .art p { font-size: 15px; color: var(--txt2); margin: 0 0 14px; line-height: 1.75; }
    .art li { font-size: 15px; color: var(--txt2); line-height: 1.75; margin-bottom: 7px; }
    .art ul, .art ol { margin: 0 0 16px; padding-left: 22px; }
    .art strong { color: var(--txt); font-weight: 700; }
    .art a { color: var(--cyan); text-decoration: none; }
    .art a:hover { text-decoration: underline; }

    /* ...and that rule reaches INTO the CTA box, where the two buttons are also
       anchors. They lost the colours the shell gives them everywhere else on the
       site, silently, on the one element the box exists for. Measured in the
       browser 2026-08-27, on all five articles: Download rendered cyan-on-blue
       at a 2.31:1 contrast ratio, against the byte-identical nav button's
       white-on-blue 4.95:1 - below the 4.5:1 AA floor and below the 3:1 large
       floor. The hover underline was landing on them too.
       Restate the shell's own values (win-setup.html, .btn-nav / .btn-nav-ghost)
       rather than inventing new ones; .art .btn-nav is 0,2,0 and wins over
       .art a at 0,1,1. Same family as the homepage's `a { color: inherit }`
       swallowing new body links - a broad link rule that a button is an anchor
       inside of. */
    .art .btn-nav { color: #fff; }
    .art .btn-nav-ghost { color: var(--txt); }
    .art .btn-nav-ghost:hover { color: #fff; }
    .art .cta-row a:hover { text-decoration: none; }
    .art code {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 12.5px; background: var(--surf2); color: var(--txt);
      border: 1px solid var(--border); border-radius: 5px; padding: 1px 6px;
    }
    .lede { font-size: 17px !important; color: var(--txt) !important; }

    /* Steps a reader follows with Canvas open in another tab.

       The marker is an inline-block in the SAME line box as the sentence,
       pulled into the gutter with a negative margin - NOT an absolutely
       positioned box. That is what makes the baseline correct for free:
       `line-height` here is the unitless 1.75 the list inherits, so an
       absolutely positioned marker at a smaller font-size resolves a
       SHORTER line box (13.2 x 1.75 = 23.1px against the row's 26.25px)
       and sits ~1.6px high. In the line box the browser aligns the two
       baselines itself, at every font-size the four shells use (15px in
       .art, 14px in .setup-card), with no per-page numbers to keep in sync.

       box-sizing is restated because the shell's reset is `*`, which does
       not match pseudo-elements - without it the padding is added to the
       30px and the text no longer lands on the list's own indent. */
    .steps { counter-reset: st; list-style: none; padding-left: 0; }
    .steps > li {
      counter-increment: st;
      padding-left: 30px; margin-bottom: 12px;
    }
    .steps > li::before {
      content: counter(st) ".";
      display: inline-block; box-sizing: border-box;
      width: 30px; margin-left: -30px; padding-right: 9px;
      text-align: right;
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 0.88em; font-weight: 600; line-height: inherit;
      font-variant-numeric: tabular-nums;
      color: var(--txt);
    }

    .note {
      border-left: 3px solid var(--cyan);
      background: rgba(56,189,248,0.06);
      border-radius: 0 var(--rad) var(--rad) 0;
      padding: 15px 18px; margin: 0 0 20px;
    }
    .note p { margin: 0; font-size: 14px; }
    .note.warn { border-left-color: #f59e0b; background: rgba(245,158,11,0.06); }
    .note.good { border-left-color: var(--green); background: rgba(52,211,153,0.06); }

    /* A wide table must scroll inside its own box, never the page. */
    .tbl-wrap { overflow-x: auto; max-width: 100%; margin: 0 0 22px; -webkit-overflow-scrolling: touch; }
    table.cmp { border-collapse: collapse; width: 100%; min-width: 640px; font-size: 13.5px; }
    table.cmp th, table.cmp td {
      border: 1px solid var(--border); padding: 10px 12px;
      text-align: left; vertical-align: top; color: var(--txt2);
    }
    table.cmp th { background: var(--surf2); color: var(--txt); font-weight: 700; }
    table.cmp td:first-child { color: var(--txt); font-weight: 600; }
    .yes { color: var(--green); font-weight: 700; }
    .no  { color: #f87171; font-weight: 700; }
    .part { color: #fbbf24; font-weight: 700; }

    details.faq {
      background: var(--surf); border: 1px solid var(--border);
      border-radius: var(--rad); padding: 0; margin-bottom: 10px;
    }
    details.faq > summary {
      cursor: pointer; padding: 15px 18px; font-size: 15px;
      font-weight: 600; color: var(--txt); list-style: none;
    }
    details.faq > summary::-webkit-details-marker { display: none; }
    details.faq > summary::after {
      content: '+'; float: right; color: var(--txt3); font-weight: 700;
      /* Text flows around this float, so without a left margin a long
         question runs right up against the '+'. Same defect, same class,
         as the flex toggles on index.html and guide.html. */
      margin-left: 12px;
    }
    details.faq[open] > summary::after { content: '\\2212'; }
    details.faq > div { padding: 0 18px 16px; }
    details.faq p { font-size: 14px; margin: 0 0 10px; }

    .cta-box {
      background: var(--surf); border: 1px solid var(--border2);
      border-radius: var(--rad-l); padding: 24px; margin: 34px 0 10px;
      text-align: center;
    }
    .cta-box h3 { margin: 0 0 8px; font-size: 18px; }
    .cta-box p { margin: 0 0 16px; font-size: 14px; }
    .cta-row { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }

    /* The byline. Google's helpful-content guidance asks whether it is
       "self-evident to your visitors who authored your content", and wants a
       byline that leads to further information - hence the #about-the-author
       link rather than a bare name. */
    .byline {
      margin: 14px 0 0; font-size: 13px; color: var(--txt3);
      display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center;
      justify-content: center;  /* the hero above it is centred */
    }
    .byline a { color: var(--txt2); text-decoration: none; border-bottom: 1px dotted var(--border2); }
    .byline a:hover { color: var(--cyan); }
    .byline .sep { color: var(--border2); }
    /* Below ~480px the byline wraps to three lines and every separator
       lands dangling at the end of a line. Stack it instead. */
    @media (max-width: 480px) {
      .byline { flex-direction: column; gap: 3px; }
      .byline .sep { display: none; }
    }

    /* The block an AI Overview lifts and a skimmer reads. It answers the title
       question completely, so it must never be a teaser for the article. */
    .short-answer {
      background: var(--surf); border: 1px solid var(--border2);
      border-left: 3px solid var(--cyan);
      border-radius: 0 var(--rad) var(--rad) 0;
      padding: 16px 20px; margin: 0 0 26px;
    }
    /* --txt, not cyan and not --txt3.  Cyan would state the accent twice
       beside the block's own cyan rail; --txt3 read as secondary, and this
       label plus the answer under it are the first thing a skimmer reads.
       Structural furniture carries the full text weight, meta does not. */
    .short-answer p.sa-label {
      margin: 0 0 6px; font-size: 12px; font-weight: 800;
      letter-spacing: 0.08em; text-transform: uppercase; color: var(--txt);
    }
    .short-answer p { margin: 0 0 10px; font-size: 15px; color: var(--txt); }
    .short-answer p:last-child { margin-bottom: 0; }

    /* Inline citation to a primary source. Cited sources are the single
       largest measured lever for a page that does not already rank; see
       marketing/BLOG_PLAN.md section 3. */
    a.src {
      color: var(--txt2); text-decoration: none;
      border-bottom: 1px solid var(--border2);
    }
    a.src:hover { color: var(--cyan); border-bottom-color: var(--cyan); }

    .author-box {
      background: var(--surf); border: 1px solid var(--border);
      border-radius: var(--rad); padding: 20px 22px; margin: 34px 0 0;
    }
    .author-box p.ab-label {
      margin: 0 0 8px; font-size: 12px; font-weight: 800;
      letter-spacing: 0.08em; text-transform: uppercase; color: var(--txt3);
    }
    .author-box p { margin: 0 0 10px; font-size: 14px; }
    .author-box p:last-child { margin-bottom: 0; }

    .toc {
      background: var(--surf); border: 1px solid var(--border);
      border-radius: var(--rad); padding: 16px 20px; margin: 0 0 30px;
    }
    /* Same reasoning as .sa-label: the label and the numbers are how a reader
       navigates, so they hold --txt.  The numbers must state it - .art li
       paints every list item --txt2 and ::marker inherits from its own li. */
    .toc p { margin: 0 0 8px; font-size: 12px; font-weight: 800;
             letter-spacing: 0.08em; text-transform: uppercase; color: var(--txt); }
    .toc ol { margin: 0; padding-left: 20px; }
    .toc li { margin-bottom: 4px; font-size: 14px; color: var(--txt); }
"""


# The index needs a card list and nothing else. Kept separate from ARTICLE_CSS
# so an article page does not carry rules for a layout it never uses.
INDEX_CSS = """
    /* ---- BLOG INDEX ---- */
    /* Wider than the 800px reading measure the ARTICLES use, because this page
       is a grid of cards rather than a column of prose: at 800px two columns
       give ~380px each, which is too narrow for a three-line title. */
    .container.wide { max-width: 1080px; width: 100%; }
    .hero h1 { line-height: 1.12; }
    .post-list { display: grid; gap: 12px; text-align: left; padding-bottom: 20px; }
    /* One column on a phone, two from 860px. 860 rather than 768 because the
       nav already collapses there, so the page has one breakpoint, not two. */
    @media (min-width: 860px) { .post-list { grid-template-columns: 1fr 1fr; } }
    /* `color: var(--txt)`, not the UA's #0000EE. The post cards are each one
       big <a>, and every piece of text inside them happens to set its own
       colour - so nothing renders blue today. That is luck, not a rule: one
       unstyled <span> added to a card would inherit 2.08:1 browser blue. Same
       class of defect as the "step-by-step walkthrough" link on mac-setup.html
       and "school search" on canvas-url-directory.html, both of which WERE
       visible. Census: `document.querySelectorAll('a')` with a computed colour
       of rgb(0,0,238), on every page. */
    /* A column, not a block, so `Read the guide` can be pushed to the bottom
       with `margin-top: auto`. In a two-column grid the cards are already the
       same HEIGHT; without this their footers still sit at different offsets,
       which is the thing that actually reads as ragged. */
    .post {
      display: flex; flex-direction: column;
      text-decoration: none; color: var(--txt);
      background: var(--surf); border: 1px solid var(--border);
      border-radius: var(--rad-l); padding: 17px 19px;
      transition: border-color .15s ease, background .15s ease, transform .15s ease;
    }
    .post:hover {
      border-color: var(--cyan); background: var(--surf2);
      transform: translateY(-2px);
    }
    /* MEASURED 2026-08-29: this block declared 12px and var(--txt3) and rendered
       at 15px and var(--txt2), because `.post p` is (0,1,1) and `.post-meta` is
       (0,1,0), so the later, more specific rule won BOTH declarations. At the
       same size as the body text but bold, uppercase and tracked, the date line
       read LARGER than the sentence describing the article - which is what the
       product owner saw. The fix is to make the two rules disjoint rather than
       to out-specify: `:not(.post-meta)` below cannot be re-broken by someone
       reordering the file, and out-specifying can. */
    p.post-meta {
      font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
      text-transform: uppercase; color: var(--txt3); margin: 0 0 7px;
    }
    .post h2 {
      font-size: clamp(16px, 1.7vw, 18px); font-weight: 800;
      letter-spacing: -0.02em; color: var(--txt); margin: 0 0 7px;
      line-height: 1.3;
    }
    .post:hover h2 { color: var(--cyan); }
    .post p:not(.post-meta) {
      font-size: 13.5px; color: var(--txt2); line-height: 1.65; margin: 0;
    }
    .post-more {
      display: inline-block; margin-top: auto; padding-top: 11px;
      font-size: 12.5px; font-weight: 700; color: var(--cyan);
    }
    /* The whole card is the link, so the arrow must not look separately
       clickable - it is decoration on a target that is already the card. */
    .post-more::after { content: " \\2192"; }
    /* Centred, like the h1 and the sub above it. The one left-aligned block on
       this page used to be a paragraph saying the articles were honest and
       checked, which is what every page claims and so tells a reader nothing;
       it was removed rather than re-centred. This line is here because these
       two pages are the only ones with NO path from a page Google has indexed. */
    .blog-tools {
      text-align: center; font-size: 13px; color: var(--txt3);
      line-height: 1.7; margin: 24px 0 0;
    }
    .blog-tools a { color: var(--cyan); text-decoration: none; }
    .blog-tools a:hover { text-decoration: underline; }
"""


def faq_markup(items: list[tuple[str, str]]) -> str:
    out = []
    for q, a in items:
        out.append(
            f'      <details class="faq">\n'
            f'        <summary>{html.escape(q)}</summary>\n'
            f'        <div><p>{a}</p></div>\n'
            f'      </details>')
    return "\n".join(out)


def faq_schema(items: list[tuple[str, str]], page_url: str) -> dict:
    """Answers are the VISIBLE text with tags stripped, never a rewrite.

    Structured data that does not match what the page says is the one way this
    markup can hurt rather than help.
    """
    def plain(a: str) -> str:
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", a))).strip()
    return {
        "@type": "FAQPage",
        "@id": page_url + "#faq",
        "inLanguage": "en",
        "isPartOf": {"@id": SITE + "#website"},
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": plain(a)}}
            for q, a in items],
    }


AUTHOR_BOX = """      <div class="author-box" id="about-the-author">
        <p class="ab-label">Who wrote this</p>
        <p><strong>BrkBuilds</strong> builds Canvas Downloader, the free
        open-source app this site is about. These guides are written from the
        engine side: what Canvas does and does not export is described from
        having implemented against the Canvas API, not from reading about it.
        The app's behaviour is documented in
        <a href="engine.html">Under the Hood</a> and the whole codebase is
        <a href="https://github.com/BrkBuilds/Canvas-Downloader" target="_blank" rel="noopener">public
        on GitHub</a>, so every claim on this page can be checked against the
        code that makes it.</p>
        <p>It is a one-person project with no company behind it. Where a page is
        uncertain it says so, and where a built-in Canvas feature or somebody
        else's tool is the better answer, it says that too.</p>
      </div>
"""


def _pretty(iso: str) -> str:
    """20 August 2026. Matches the format the blog index already prints."""
    return datetime.date.fromisoformat(iso).strftime("%d %B %Y").lstrip("0")


def byline(published: str, modified: str) -> str:
    """A visible byline and date.

    Both were missing entirely: the dates existed in PAGES and were rendered on
    the index but never on the article itself, so a reader had no way to tell
    whether a page was current or who stood behind it.

    Updated is shown only when it differs from published. Printing "Updated"
    with the publication date is the kind of small untruth that costs a reader
    their trust in every other number on the page.
    """
    bits = ['<span>By <a href="#about-the-author">BrkBuilds</a>, who builds the app</span>',
            '<span class="sep">&middot;</span>',
            f'<span>Published <time datetime="{published}">{_pretty(published)}</time></span>']
    if modified != published:
        bits += ['<span class="sep">&middot;</span>',
                 f'<span>Updated <time datetime="{modified}">{_pretty(modified)}</time></span>']
    return '<p class="byline">' + "".join(bits) + "</p>"


def build(slug: str, *, title: str, description: str, h1: str, lede: str,
          crumb: str, body: str, faq: list[tuple[str, str]],
          extra_nodes: list[dict], published: str, modified: str,
          answer: str = "", page_css: str = "") -> Path:
    """``page_css`` is for a page that needs a device the other twelve do not.

    It is appended AFTER ``ARTICLE_CSS`` inside the same ``<style>``, so a page
    rule can override an article rule without an ``!important``. It defaults to
    empty, so the twelve pages that do not use it carry not one extra byte -
    which is the reason this is a parameter rather than another block bolted on
    to the shared stylesheet.
    """
    css, nav, foot, tail = _shell()
    url = SITE + slug
    graph = [
        # These two are REFERENCED by @id below (author, publisher, isPartOf).
        # A bare {"@id": ...} pointing at a node that is not in the SAME page's
        # graph resolves to nothing - Google reads the graph per page, not per
        # site - so the article would validate as having an author with no name.
        # Defining them here costs a few hundred bytes and makes every reference
        # resolvable on its own page.
        {"@type": "Person", "@id": SITE + "#author", "name": "BrkBuilds",
         "url": "https://github.com/BrkBuilds",
         "sameAs": ["https://github.com/BrkBuilds", "https://ko-fi.com/brkbuilds"]},
        {"@type": "WebSite", "@id": SITE + "#website", "url": SITE,
         "name": "Canvas Downloader", "inLanguage": "en"},
        # Home > Blog > article. The Blog rung was added when the index page
        # was, because a breadcrumb that skips a real level is a breadcrumb
        # that describes a site structure the visitor cannot navigate.
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Canvas Downloader", "item": SITE},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": SITE + "blog.html"},
            {"@type": "ListItem", "position": 3, "name": crumb, "item": url}]},
        {"@type": "Article", "@id": url + "#article", "headline": h1,
         "description": description, "inLanguage": "en",
         "datePublished": published, "dateModified": modified,
         "author": {"@id": SITE + "#author"},
         "publisher": {"@id": SITE + "#author"},
         "mainEntityOfPage": url,
         "image": OG},
        faq_schema(faq, url),
        *extra_nodes,
    ]
    ld = json.dumps({"@context": "https://schema.org", "@graph": graph},
                    indent=2, ensure_ascii=False)
    ld = "\n".join("  " + ln for ln in ld.splitlines())

    short_answer = ""
    if answer:
        short_answer = ('      <div class="short-answer">\n'
                        '        <p class="sa-label">Short answer</p>\n'
                        + answer + "      </div>\n")

    e = html.escape
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{e(title)}</title>
  <link rel="canonical" href="{url}" />
  <meta property="og:url" content="{url}" />
  <meta name="description" content="{e(description)}" />
  <meta property="og:type" content="article" />
  <meta property="og:locale" content="en_US" />
  <meta property="og:site_name" content="Canvas Downloader" />
  <meta property="og:title" content="{e(title)}" />
  <meta property="og:description" content="{e(description)}" />
  <meta property="og:image" content="{OG}" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt" content="{e(OG_ALT)}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{e(title)}" />
  <meta name="twitter:description" content="{e(description)}" />
  <meta name="twitter:image" content="{OG}" />
  <meta name="twitter:image:alt" content="{e(OG_ALT)}" />
  <script type="application/ld+json">
{ld}
  </script>
  <meta name="theme-color" content="#0b0c14" />
  <link rel="icon" type="image/x-icon" href="icon.ico" />
  <link rel="apple-touch-icon" href="icon.png" />
  <!-- Self-hosted fonts: no request leaves the visitor's browser. See fonts.css. -->
  <link rel="preload" as="font" type="font/woff2" href="assets/fonts/inter-latin.woff2" crossorigin />
  <link rel="stylesheet" href="fonts.css" />
{css[:-len("</style>")]}{ARTICLE_CSS}{page_css}  </style>
</head>
<body>
{nav}

  <div class="hero">
    <div class="container wide">
      <h1>{h1}</h1>
      <p class="sub">{lede}</p>
      {byline(published, modified)}
    </div>
  </div>

  <div class="container wide">
    <div class="art">
{short_answer}
{body}

      <h2 id="faq">Common questions</h2>
{faq_markup(faq)}

{AUTHOR_BOX}    </div>
  </div>

{foot}

{tail}</body>
</html>
"""
    out = DOCS / slug
    out.write_text(page, encoding="utf-8", newline="\r\n")
    return out


def _reading_minutes(body: str) -> int:
    """Derived from the prose, so it cannot go stale the way a typed one does."""
    words = len(re.sub(r"<[^>]+>", " ", body).split())
    return max(1, round(words / 200))


def build_index(pages: list[dict]) -> Path:
    """docs/blog.html - the index every article link in the footer now points at.

    GENERATED, for the same reason the articles are. Three loose article links
    in the footer of fourteen hand-maintained pages does not scale: every new
    article means fourteen edits, and nothing tells you when one is missed. One
    "Blog" entry pointing here means adding a dict to PAGES is the whole job.

    Schema is CollectionPage + ItemList rather than Blog + BlogPosting. The
    articles already declare an Article node at <url>#article, and declaring a
    second typed node for the same URL from a different page is how you end up
    with two descriptions of one document competing. An ItemList only points.
    """
    css, nav, foot, tail = _shell()
    url = SITE + "blog.html"
    title = "Blog: Canvas Guides and How-Tos"
    description = ("Guides to getting your course material out of Canvas: every "
                   "download method, lecture recordings, feedback, and what to "
                   "do with the files afterwards.")

    newest_first = sorted(pages, key=lambda p: p["published"], reverse=True)

    graph = [
        {"@type": "Person", "@id": SITE + "#author", "name": "BrkBuilds",
         "url": "https://github.com/BrkBuilds",
         "sameAs": ["https://github.com/BrkBuilds", "https://ko-fi.com/brkbuilds"]},
        {"@type": "WebSite", "@id": SITE + "#website", "url": SITE,
         "name": "Canvas Downloader", "inLanguage": "en"},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Canvas Downloader", "item": SITE},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": url}]},
        {"@type": "CollectionPage", "@id": url + "#page", "url": url,
         "name": title, "description": description, "inLanguage": "en",
         "isPartOf": {"@id": SITE + "#website"},
         "about": "Downloading and keeping Canvas course material",
         "mainEntity": {
             "@type": "ItemList",
             "itemListOrder": "https://schema.org/ItemListOrderDescending",
             "numberOfItems": len(newest_first),
             "itemListElement": [
                 {"@type": "ListItem", "position": i, "url": SITE + p["slug"],
                  "name": p["title"]}
                 for i, p in enumerate(newest_first, 1)]}},
    ]
    ld = json.dumps({"@context": "https://schema.org", "@graph": graph},
                    indent=2, ensure_ascii=False)
    ld = "\n".join("  " + ln for ln in ld.splitlines())

    e = html.escape
    cards = []
    for p in newest_first:
        when = datetime.date.fromisoformat(p["published"]).strftime("%d %B %Y").lstrip("0")
        cards.append(
            f'      <a class="post" href="{p["slug"]}">\n'
            f'        <p class="post-meta">{when} &middot; '
            f'{_reading_minutes(p["body"])} min read</p>\n'
            f'        <h2>{e(p["h1"])}</h2>\n'
            f'        <p>{e(p["description"])}</p>\n'
            f'        <span class="post-more">Read the guide</span>\n'
            f'      </a>')
    cards = "\n".join(cards)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{e(title)}</title>
  <link rel="canonical" href="{url}" />
  <meta property="og:url" content="{url}" />
  <meta name="description" content="{e(description)}" />
  <meta property="og:type" content="website" />
  <meta property="og:locale" content="en_US" />
  <meta property="og:site_name" content="Canvas Downloader" />
  <meta property="og:title" content="{e(title)}" />
  <meta property="og:description" content="{e(description)}" />
  <meta property="og:image" content="{OG}" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt" content="{e(OG_ALT)}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{e(title)}" />
  <meta name="twitter:description" content="{e(description)}" />
  <meta name="twitter:image" content="{OG}" />
  <meta name="twitter:image:alt" content="{e(OG_ALT)}" />
  <script type="application/ld+json">
{ld}
  </script>
  <meta name="theme-color" content="#0b0c14" />
  <link rel="icon" type="image/x-icon" href="icon.ico" />
  <link rel="apple-touch-icon" href="icon.png" />
  <!-- Self-hosted fonts: no request leaves the visitor's browser. See fonts.css. -->
  <link rel="preload" as="font" type="font/woff2" href="assets/fonts/inter-latin.woff2" crossorigin />
  <link rel="stylesheet" href="fonts.css" />
{css[:-len("</style>")]}{INDEX_CSS}  </style>
</head>
<body>
{nav}

  <div class="hero">
    <div class="container wide">
      <h1>Blog</h1>
      <p class="sub">Practical guides to getting your course material out of
      Canvas, and what to do with it once you have it.</p>
    </div>
  </div>

  <div class="container wide">
    <div class="post-list">
{cards}
    </div>

    <p class="blog-tools">Two reference tools rather than guides:
    <a href="canvas-url-directory.html">the Canvas URL directory</a>, and
    <a href="canvas-data.html">the same 4,757 institutions as CSV and JSON</a>.</p>
  </div>

{foot}

{tail}</body>
</html>
"""
    out = DOCS / "blog.html"
    out.write_text(page, encoding="utf-8", newline="\r\n")
    return out


# --------------------------------------------------------------- content ----
# Kept in this file rather than in HTML so the two pages cannot drift in
# structure, and so a copy change is a diff of prose instead of a diff of markup.

from guide_pages_content import PAGES  # noqa: E402  (content lives beside this)


def main() -> None:
    for spec in PAGES:
        out = build(**spec)
        text = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>",
                                              "", out.read_text(encoding="utf-8"), flags=re.S))
        print(f"  {out.name:44s} {len(text.split()):5d} words  "
              f"{out.stat().st_size/1024:6.1f} KB")

    idx = build_index(PAGES)
    print(f"  {idx.name:44s} {len(PAGES):5d} posts  "
          f"{idx.stat().st_size/1024:6.1f} KB")


if __name__ == "__main__":
    main()
