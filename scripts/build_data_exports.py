"""Publish the institution list as data, and the page that documents it.

WHY THIS EXISTS
---------------
Until 2026-08-29 nothing under ``docs/`` was machine-readable: no CSV, no JSON,
just HTML. The one dataset this project owns - 4,757 Canvas hostnames, each
proven live against ``/api/v1/users/self`` at generation time - reached the web
only as a 957 KB HTML table in ``canvas-url-directory.html``.

A builder who consumes a CSV cites it. A builder who scrapes a table copies it.
That is the whole argument for this file, and it is why the export carries a
licence and a stated method rather than being a bare dump.

SIZE THE WIN HONESTLY. GitHub renders README links ``rel="nofollow"``, measured
2026-08-28, so a repository citing this passes no ranking signal. What it passes
is discovery and credibility with people who build things, plus a chance of a
dofollow wherever a dataset gets written up. It is not a ranking play.

THE HUMAN PAGE LIVES AT THE ROOT, NOT IN ``docs/data/``
-------------------------------------------------------
``_shell()`` emits nav and footer links as bare filenames (``index.html``,
``guide.html``). A page served from ``docs/data/`` would resolve every one of
them against ``/data/`` and break the entire site chrome, silently, in a way
that looks fine in the source. So ``canvas-data.html`` sits beside every other
page and only the machine files go in the subfolder.

NO CTA BOX ON THIS PAGE, deliberately. Census 2026-08-29: 12 of 12 generated
articles end in a Download button, which is why no page here is citable by the
people who actually publish links. This page is addressed to a builder, an
assistant or a help desk, and it sells nothing. Do not add one later.

THE DATE IS DERIVED, NEVER RESTATED. ``shared/institutions.py`` carries no
generation timestamp, so the verification date is read from git history for that
one file - the same discipline ``scripts/ping_indexnow.py`` uses to find its own
IndexNow key rather than hardcoding a second copy of it. If git cannot answer,
the date is omitted rather than guessed: a wrong provenance date on a dataset is
worse than none.

Run:  python scripts/build_data_exports.py
"""
from __future__ import annotations

import csv
import html
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA_DIR = DOCS / "data"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from site_shell import _shell, SITE, OG, OG_ALT  # noqa: E402
from shared.institutions import DATA, COUNT  # noqa: E402

SLUG = "canvas-data.html"
CSV_NAME = "data/canvas-hosts.csv"
JSON_NAME = "data/canvas-hosts.json"

LICENCE = "CC BY 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
ATTRIBUTION = "Canvas Downloader, canvasdownloader.app"

TITLE = "Canvas Host Data: %s Verified Institutions as CSV and JSON" % f"{COUNT:,}"
DESC = ("An open dataset of %s institutions' Canvas hostnames, each verified "
        "live against the Canvas API, as CSV and JSON under CC BY 4.0."
        % f"{COUNT:,}")
H1 = "Canvas host data"
LEDE = ("The list behind the directory, as files you can read with something "
        "other than a browser. %s institutions, verified live, %s."
        % (f"{COUNT:,}", LICENCE))

e = html.escape

FIELDS = [
    ("institution", "The institution's display name, as the app shows it."),
    ("canvas_host", "The hostname that answers Canvas's API. No scheme, no path."),
    ("country", "ISO 3166-1 alpha-2, or empty. See the note on how it is set."),
    ("curated", "1 for a hand-checked seed, 0 for a row taken from the crawl "
                "under its own name."),
]


def verified_date() -> str:
    """Last commit date of the data module, or "" when git cannot answer.

    A dataset's provenance date has to be true or absent. CI clones shallow, so
    an empty answer here is legitimate rather than an error.
    """
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ad", "--date=short", "--",
             "shared/institutions.py"],
            cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def coverage() -> tuple[int, int]:
    """Rows carrying a country, and how many distinct countries."""
    known = [r[2] for r in DATA if r[2]]
    return len(known), len(set(known))


def write_csv(path: pathlib.Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([name for name, _ in FIELDS])
        for name, host, cc, flags in DATA:
            w.writerow([name, host, cc, 1 if "s" in flags else 0])
    return path.stat().st_size


def write_json(path: pathlib.Path, when: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "name": "Canvas host data",
        "description": ("Institutions and the Canvas hostname each one uses. "
                        "Every host answered Canvas's own unauthenticated "
                        "/api/v1/users/self payload when the list was built."),
        "source": SITE + SLUG,
        "licence": LICENCE,
        "licence_url": LICENCE_URL,
        "attribution": ATTRIBUTION,
        "verified": when,
        "count": COUNT,
        "fields": {name: doc_ for name, doc_ in FIELDS},
        "exhaustive": False,
        "institutions": [
            {"institution": name, "canvas_host": host,
             "country": cc, "curated": bool("s" in flags)}
            for name, host, cc, flags in DATA
        ],
    }
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path.stat().st_size


PAGE_CSS = """
  <style>
    /* The win-setup shell defines NO `a` rule, so an un-styled link on a page
       built from it renders in the UA's #0000EE at about 2:1 on this
       background. `canvas-url-directory.html` inlined a colour on each link one
       at a time and missed three. One rule instead - there is no CTA box on
       this page for it to reach into. */
    .art a { color: var(--cyan); }
    /* WCAG 1.4.1 / Lighthouse link-in-text-block: at rest these links were told
       apart from the sentence around them by COLOUR ALONE. Measured 2026-08-31:
       --cyan #38bdf8 against body --txt2 #bfc3c9 is 1.21:1 and axe needs 3.0:1 to
       pass on colour, which no cyan reaches - the lightest tried, #a5f3fc, is
       1.42:1 - because both are light colours on a dark ground. So the cue has to
       be non-colour, and an underline is it. Scoped to PROSE on purpose: a TOC is
       a list of links rather than a text block, and the CTA row and the nav
       buttons are buttons, so all three keep their own treatment below. */
    .art p a, .art li a {
      text-decoration: underline;
      text-underline-offset: 0.18em;
      text-decoration-thickness: 1px;
    }
    .art .toc a, .art .cta-row a, .art .byline a { text-decoration: none; }
    .dsch-wrap { overflow-x: auto; border-radius: 12px;
      border: 1px solid rgba(255,255,255,.09); margin: 0 0 22px; }
    table.dsch { width: 100%; border-collapse: collapse; font-size: 14px;
      margin: 0; }
    table.dsch th, table.dsch td { padding: 9px 14px; text-align: left;
      border-bottom: 1px solid rgba(255,255,255,.06); vertical-align: top; }
    table.dsch th { font-size: 12px; letter-spacing: .06em; text-transform: uppercase;
      color: var(--txt3); font-weight: 800; }
    table.dsch td:first-child { font-family: ui-monospace, Menlo, Consolas, monospace;
      color: var(--txt); white-space: nowrap; }
    .dl-row { display: flex; gap: 12px; flex-wrap: wrap; margin: 0 0 22px; }
    .dl-card { flex: 1 1 240px; border: 1px solid rgba(255,255,255,.09);
      border-radius: 12px; padding: 16px 18px; background: rgba(255,255,255,.03); }
    .dl-card h2 { margin: 0 0 4px; font-size: 16px; }
    .dl-card p { margin: 0 0 10px; font-size: 13px; color: var(--txt2); }
    .dl-card .sz { font-family: ui-monospace, Menlo, Consolas, monospace;
      font-size: 12px; color: var(--txt3); }
    .cite { border: 1px solid rgba(255,255,255,.09); border-radius: 10px;
      padding: 14px 16px; font-size: 14px; color: var(--txt2);
      background: rgba(255,255,255,.03); margin: 0 0 22px; }
  </style>
"""


def _j(s: str) -> str:
    return json.dumps(s)


def build(csv_kb: float, json_kb: float, when: str) -> pathlib.Path:
    css, nav, foot, tail = _shell()
    url = SITE + SLUG
    known, countries = coverage()
    ld = """{
  "@context": "https://schema.org",
  "@graph": [
    {"@type": "WebSite", "@id": "%s#website", "url": "%s",
     "name": "Canvas Downloader", "inLanguage": "en"},
    {"@type": "Dataset", "@id": "%s#dataset", "url": "%s",
     "name": %s, "description": %s,
     "license": "%s", "creator": {"@id": "%s#website"},
     "isAccessibleForFree": true, "inLanguage": "en",
     "distribution": [
       {"@type": "DataDownload", "encodingFormat": "text/csv",
        "contentUrl": "%s"},
       {"@type": "DataDownload", "encodingFormat": "application/json",
        "contentUrl": "%s"}
     ]},
    {"@type": "BreadcrumbList", "@id": "%s#crumbs", "itemListElement": [
      {"@type": "ListItem", "position": 1, "name": "Home", "item": "%s"},
      {"@type": "ListItem", "position": 2, "name": "Canvas host data", "item": "%s"}
    ]}
  ]
}""" % (SITE, SITE, url, url, _j(TITLE), _j(DESC), LICENCE_URL, SITE,
        SITE + CSV_NAME, SITE + JSON_NAME, url, SITE, url)

    schema_rows = "\n".join(
        '            <tr><td>%s</td><td>%s</td></tr>' % (e(n), e(d))
        for n, d in FIELDS)

    when_txt = ("Verified %s, the last time the list was rebuilt." % e(when)
                if when else
                "The verification date could not be read from this checkout.")

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{e(TITLE)}</title>
  <meta name="description" content="{e(DESC)}" />
  <link rel="canonical" href="{url}" />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="{url}" />
  <meta property="og:title" content="{e(TITLE)}" />
  <meta property="og:description" content="{e(DESC)}" />
  <meta property="og:image" content="{OG}" />
  <meta property="og:image:alt" content="{e(OG_ALT)}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{e(TITLE)}" />
  <meta name="twitter:description" content="{e(DESC)}" />
  <meta name="twitter:image" content="{OG}" />
  <script type="application/ld+json">
{ld}
  </script>
  <meta name="theme-color" content="#0b0c14" />
  <link rel="icon" type="image/x-icon" href="icon.ico" />
  <link rel="apple-touch-icon" href="icon.png" />
  <link rel="preload" as="font" type="font/woff2" href="assets/fonts/inter-latin.woff2" crossorigin />
  <link rel="stylesheet" href="fonts.css" />
{css}
{PAGE_CSS}
</head>
<body>
{nav}

  <main>

  <div class="hero">
    <div class="container wide">
      <h1>{H1}</h1>
      <p class="sub">{e(LEDE)}</p>
    </div>
  </div>

  <div class="container wide">
    <div class="art">
      <p>Canvas is run separately by every institution that uses it, so there is
      no central list of where it lives. Instructure operates a school search,
      and it renders its results with JavaScript, so no hostname on it is text
      that anything other than a browser can read. This is the same information
      as a file.</p>

      <div class="dl-row">
        <div class="dl-card">
          <h2><a href="{CSV_NAME}">canvas-hosts.csv</a></h2>
          <p>One row per institution, UTF-8, header row included.</p>
          <span class="sz">{csv_kb:.0f} KB &middot; {COUNT:,} rows</span>
        </div>
        <div class="dl-card">
          <h2><a href="{JSON_NAME}">canvas-hosts.json</a></h2>
          <p>The same rows, plus the licence, the method and the field notes.</p>
          <span class="sz">{json_kb:.0f} KB &middot; {COUNT:,} objects</span>
        </div>
      </div>

      <h2 id="method">How it was built</h2>

      <p>Every hostname was requested at
      <code>/api/v1/users/self</code> and kept only if it answered with Canvas's
      own unauthenticated payload. That check is the point of the list: a
      university home page, a parked domain and an SSO portal all answer an
      ordinary request, so a naive reachability test passes things that are not
      Canvas at all. {when_txt}</p>

      <p>The list is generated by
      <code>scripts/build_institution_list.py</code> in the
      <a href="https://github.com/BrkBuilds/Canvas-Downloader"
      rel="nofollow noopener" target="_blank">public repository</a>, and these
      files are generated from it by
      <code>scripts/build_data_exports.py</code>. Both are readable, so the
      method is checkable rather than asserted.</p>

      <h2 id="fields">Fields</h2>

      <div class="dsch-wrap">
        <table class="dsch">
          <thead>
            <tr><th>Field</th><th>What it holds</th></tr>
          </thead>
          <tbody>
{schema_rows}
          </tbody>
        </table>
      </div>

      <h2 id="limits">What this data is not</h2>

      <p><strong>It is not exhaustive, and a missing school is not an
      unsupported one.</strong> Canvas is used by many thousands of
      institutions and this covers the largest and best known. Instructure's own
      <a href="https://www.instructure.com/canvas/login" rel="nofollow noopener"
      target="_blank">school search</a> is the authoritative source.</p>

      <p><strong>Country is known for {known:,} of the {COUNT:,} rows, across
      {countries} countries.</strong> It is proven by the domain's country code
      where there is one, and otherwise inferred from unambiguous markers in the
      institution's own name. An empty value means unknown rather than anything
      about the institution, so do not read the blanks as a geography.</p>

      <p><strong>It is a snapshot.</strong> Institutions move Canvas between
      hostnames, and a row that was live when it was checked can stop being
      live afterwards. Treat the verification date as the claim's expiry, not
      as a guarantee.</p>

      <h2 id="licence">Licence and citation</h2>

      <p>The compilation is published under
      <a href="{LICENCE_URL}" rel="license noopener" target="_blank">{LICENCE}</a>.
      Use it for anything, including commercially, as long as the compilation is
      credited.</p>

      <div class="cite">{e(ATTRIBUTION)}{', ' + e(when) if when else ''} &middot;
      <a href="{url}">{url}</a> &middot; {LICENCE}</div>

      <p>If you are reading this as a person rather than as a script, the same
      list is browsable and searchable in the
      <a href="canvas-url-directory.html">Canvas URL directory</a>, and what the
      hostname is actually for is explained in
      <a href="canvas-access-token-explained.html">what a Canvas access token
      is</a>.</p>

      <p>If you find a hostname here that is wrong, or a school that is missing,
      the repository's issue tracker is the place for it and corrections are
      welcome.</p>
    </div>
  </div>

  </main>

{foot}

{tail}
</body>
</html>
"""
    out = DOCS / SLUG
    out.write_text(page, encoding="utf-8", newline="\r\n")
    return out


def main() -> None:
    when = verified_date()
    csv_bytes = write_csv(DATA_DIR / "canvas-hosts.csv")
    json_bytes = write_json(DATA_DIR / "canvas-hosts.json", when)
    page = build(csv_bytes / 1024, json_bytes / 1024, when)
    known, countries = coverage()
    print("  canvas-hosts.csv   %7.1f KB  %d rows" % (csv_bytes / 1024, COUNT))
    print("  canvas-hosts.json  %7.1f KB  %d objects" % (json_bytes / 1024, COUNT))
    print("  %-18s %7.1f KB" % (page.name, page.stat().st_size / 1024))
    print("  country known on %d of %d rows, %d countries, verified %s"
          % (known, COUNT, countries, when or "unknown"))


if __name__ == "__main__":
    main()
