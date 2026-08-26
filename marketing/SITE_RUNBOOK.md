# Site runbook

How to change anything under `docs/` without breaking it. Read this before
editing the website. The traps below were each paid for once.

---

## 1. How the site is built

There is **no build step and no framework**. `docs/` is served directly by
GitHub Pages at `canvasdownloader.app` (`docs/CNAME`), with `.nojekyll` so files
are published as-is.

Every page inlines **its own copy** of the nav, the footer and a ~6.5 KB
stylesheet. That is a deliberate trade for a small hand-written site, and it has
one consequence you must respect: **a change to the nav or footer has to be made
in every page**, and nothing tells you when one is missed.

| File | Role |
|---|---|
| `docs/index.html` | Homepage, ~200 KB, heavily tuned. Treat carefully. |
| `docs/guide.html` | How it works. 7,300 words, 13 FAQ entries. |
| `docs/engine.html` | Under the hood. Deep technical explainer; has its own minimal footer on purpose. |
| `docs/releases.html` | Downloads. **Static-first**, see section 3. |
| `docs/win-setup.html` | **The shell source of truth.** Smallest page; the guide generator lifts its CSS, nav and footer. |
| `docs/mac-setup.html` | macOS setup. Contains the wizard (`mac-wizard.js`). |
| `docs/blog.html` | **Generated** index of every article, newest first. Do not hand-edit. |
| `docs/how-to-download-all-canvas-files.html` | **Generated.** Do not hand-edit. |
| `docs/canvas-access-after-graduation.html` | **Generated.** Do not hand-edit. |
| `docs/download-panopto-lecture-recordings.html` | **Generated.** Do not hand-edit. |
| `docs/save-canvas-assignment-feedback.html` | **Generated.** Do not hand-edit. |
| `docs/canvas-files-into-notebooklm.html` | **Generated.** Do not hand-edit. |
| `docs/404.html` | Must use **root-relative** paths, see section 5. |
| `docs/thanks-win.html`, `thanks-mac.html` | `noindex` download confirmations, correctly excluded from the sitemap. |
| `docs/llms.txt` | Factual brief for AI assistants. |
| `docs/.well-known/security.txt` | RFC 9116. **Verify it serves after the first deploy**; GitHub Pages and dot-directories are worth confirming rather than assuming. Its `Expires` field is required and is set to 2027-08-20. |

**The homepage's six demo videos have their own runbook: [PILLAR_VIDEOS.md](PILLAR_VIDEOS.md).** Read it before touching any `.mp4` or poster
under `docs/assets/`. Encoding settings, the deferred-poster rule that keeps them off
the LCP path, and the poster-frame privacy rule all live there rather than here.

## 2. Adding or editing a guide page

The search-facing pages **and their index** are generated, so they cannot drift
from the rest of the site:

```
scripts/guide_pages_content.py   <- the prose, and the page definitions
scripts/build_guide_pages.py     <- the shell, the article CSS, the schema,
                                    and build_index() -> docs/blog.html
python scripts/build_guide_pages.py
```

Edit the prose in the content file and re-run. To add a page, append a dict to
`PAGES` with `slug`, `title`, `description`, `h1`, `lede`, `crumb`, `body`,
`faq`, `extra_nodes`, `published`, `modified`.

**`docs/blog.html` is derived from `PAGES`**, newest `published` first, so the
index, the card titles, the dates and the reading times all follow from that one
dict. Reading time is computed from the body, so it cannot go stale the way a
typed one does.

Then, by hand:

1. Add it to `docs/sitemap.xml`.
2. Add it to `docs/llms.txt`, which is what an assistant reads. A guide missing
   from that list is invisible to the surface the register says already
   summarises this product from somewhere else.
3. `python -m pytest tests/test_website_internal_links.py` will fail until the
   sitemap knows about it. That is the point.

**You do NOT touch the footer any more, and that is the whole reason the blog
index exists.** Article links used to sit loose in the footer of fourteen
hand-maintained pages, so every new article was fourteen edits with nothing to
tell you when one was missed. There is now a single **Blog** entry pointing at
the index. If you ever need to change the footer itself, the old rule still
applies: edit `win-setup.html` **first** (the generator lifts the shell from it)
and then every other hand-written page.

**Constraints the generator already enforces, do not undo them:**

- The nav's `active` class is stripped. A guide page is none of the nav's four
  destinations, and lifting the shell verbatim once told every visitor to a
  guide page that they were on the setup page.
- `Person` and `WebSite` nodes are **defined**, not just referenced. Google
  resolves `@id` per page, so a bare reference to a node on another page gives
  you an author with no name.
- FAQ schema answers are the **visible text with tags stripped**, never a
  rewrite. Structured data that disagrees with the page is the one way this
  markup hurts.
- Titles stay at or under ~60 characters and descriptions at ~148, or they
  truncate in results.

## 3. Publishing a release

`docs/releases.html` is **static-first**: the version, sizes, dates, download
URLs and release history are written into the HTML, and the page's own script
overwrites them from the GitHub API when it can. It is static-first because a
crawler used to see only "Loading the latest release...", and because a visitor
whose network blocks `api.github.com` used to get an error instead of a
download.

The page carries a maintenance comment listing the six things to edit. In short:

1. Both version pills (`#win-ver`, `#mac-ver`), format `v2.0.1`.
2. Both download `href`s (`#win-exe`, `#mac-dmg`).
   **THESE MUST STAY `<a href="...">`.** They were once `<button>` and both
   downloads were silently dead, because the script assigns `element.href` and a
   button has no href behaviour. Style the anchor; never change the tag.
3. The `Version X.Y.Z - N MB - Released <date>` line in each card
   (`.dl-meta`). Take the real byte size from the release asset.
4. Move the outgoing version into a new `.rel-row` at the top of `#older-list`.
5. `softwareVersion`, `downloadUrl`, `datePublished` and `fileSize` in the
   JSON-LD, on **both** `releases.html` and `index.html`.
6. `<lastmod>` in `docs/sitemap.xml`.

**The version on the website is the newest shipped TAG, never `version.py`.**
`version.py` is deliberately kept ahead of every tag
(`tests/test_version_leads_tags.py`) because the in-app update banner compares
the newest tag against the running build. Those two numbers are not the same and
must not be made the same. `tests/test_website_advertises_shipped_version.py`
fails if the site drifts.

**Do not forget the release notes themselves.** They are a content surface
GitHub indexes, they are where "Releases" lands people, and
`scripts/migrate_repo_urls.py` cannot reach them because they live on GitHub and
not in the tree. See `PLAYBOOK.md` section 1b.

## 4. Which tests guard what

All fast, all offline.

| Test | Guards |
|---|---|
| `tests/test_website_download_links.py` | Nothing that receives a scripted `.href` may be a non-anchor; both installers reachable without JavaScript; version pills are static text. |
| `tests/test_website_advertises_shipped_version.py` | Every stated version equals the newest git tag; `version.py`'s in-development number never leaks. Skips when tags are invisible. |
| `tests/test_website_internal_links.py` | Every internal `href`/`src` resolves; no pre-transfer path prefix; 404 uses root-relative paths; every sitemap URL exists and is indexable; no page is missing from the sitemap. |
| `tests/test_no_stale_repo_urls.py` | No file links to the old owner or old Pages host; the installer's three URLs are separate and absolute. |
| `tests/test_website_login_claims.py` | Pre-existing: what the site says about logging in is still true of the app. |
| `tests/test_website_noscript_content.py` | Nothing on `index`, `guide` or `engine` is `opacity: 0` to a crawler that runs no JavaScript. The reveal animation is gated on `html.js`, set from an inline `<head>` script only when `IntersectionObserver` exists. Pins the additive form: hiding on `html.js .reveal` instead would outrank `.reveal.vis` and nothing would ever be revealed. |
| *(adoption figures)* | **Deliberately untested.** The published figure is a rounded-down floor on a number that only grows, so any hard-coded ceiling is wrong the week after it is written. `docs/index.html` and `docs/llms.txt` are the two surfaces; change them together by hand. See `FINDINGS.md`. |

10 of 10 mutations of the real code are caught by these. **Re-run the mutation
pass, not just the suite, after touching any of them**, per this repo's standing
rule: a passing test proves nothing until it has been shown to fail.

## 5. Traps, each paid for once

- **`docs/404.html` must use root-relative paths** (`/guide.html`). It is served
  for a URL at any depth, so a relative path resolves against whatever bogus
  directory the visitor typed. All nine of its links were 404 for a period after
  the domain migration and nobody noticed, because nobody visits the 404 page on
  purpose.
- **Every page under `docs/` is CRLF.** A multi-line anchor written with `\n`
  never matches and reads as a missing guard. Read and write with
  `newline=''` and build replacement strings with `\r\n`.
- **`docs/llms.txt` is LF, unlike every `.html` page.** The rule above is about
  the pages; a patch that assumes CRLF for the whole directory fails on this one
  file, and the assertion that catches it is the only reason you find out. Detect
  the newline from the file you are editing rather than hard-coding either.
- **A hard-wrapped file breaks phrase matching.** `llms.txt` wraps at ~80
  columns, so "June 2026" can straddle a line break and a literal search for it
  fails against copy that is perfectly correct. Normalise whitespace first.
- **A `<button>` does not inherit `color` from `body`.** Converting an `<a>` to
  a button silently drops any `.parent a` styling and falls back to the UA
  colour, which on this dark site is black on black.
- **`preload="none"` is ignored while `autoplay` is present.** To defer a video
  you must withhold the `src`. See the bridge comments in `index.html`.
- **Testing a deferred video inside a closed `<details>` looks like a failure.**
  `scrollIntoView` on an element in a collapsed disclosure does nothing and the
  observer correctly reports no intersection. Open the disclosure first.
  `mac-setup.html`'s video is in exactly this position.
- **`<body>` is a column flex container.** A child's width is the *cross* size
  and is resolved from content unless it is definite, so a wide table's
  `min-width` can stretch the entire page sideways on mobile. `width: 100%` on
  the container fixes it; **`min-width: 0` was measured and does not**.
- **A wide table must scroll inside its own `overflow-x: auto` box**, never the
  page, and that box needs `tabindex="0"`, `role="region"` and an `aria-label`.
- **HTML comments are not markup.** A test that greps the raw file will match
  the maintenance comment in `releases.html`, which quotes the very elements it
  is looking for, and report a fault that is not there. Strip comments first.
- **The old GitHub Pages host does not redirect.** `github.com/<old-owner>/...`
  is 301'd by GitHub; `<old-owner>.github.io/<old-repo>/...` simply 404s.

## 6. How to measure

Use an independent Playwright instance; the MCP browser may be held by another
session.

**Core Web Vitals must be measured on a mobile profile**, because Google's field
data is predominantly mobile. Desktop-unthrottled numbers on this site are
flattering and were once reported as a clean bill of health while the mobile
number was in the POOR band.

```python
ctx = b.new_context(viewport={"width":390,"height":844}, is_mobile=True, has_touch=True)
cdp = ctx.new_cdp_session(pg)
cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
cdp.send("Network.emulateNetworkConditions", {"offline": False,
    "downloadThroughput": 1.6*1024*1024/8, "uploadThroughput": 750*1024/8, "latency": 150})
```
Then read LCP and CLS with a buffered `PerformanceObserver`.

**To A/B a fix**, copy `docs/` into two directories, patch one, serve both with
`http.server` on different ports and measure each under the same throttle. That
is how `preload="none"` was shown to do nothing before it could be shipped.

**To test a page the way a crawler sees it**, use
`browser.new_context(java_script_enabled=False)`.

**To test a page whose JS calls the GitHub API**, stub the response with
`page.route` using a real captured payload. Do not conclude a page is broken
from a blocked API call; check whether the API answers with
`Access-Control-Allow-Origin: *` from `curl` first.

**Baseline numbers, 2026-08-20, for comparison:**

| Metric | Desktop | Mobile (4x CPU, 1.6 Mbps) |
|---|---|---|
| TTFB | 186 ms | 180 ms |
| LCP | 212 to 1068 ms | 2764 ms (was 5300) |
| CLS | 0.0092 | 0.0013 (was 0.0219) |

## 7. Deploying

Commit and push. GitHub Pages serves `docs/` from the default branch. Then:

1. Load `https://canvasdownloader.app/releases.html` and click both download
   buttons. This is the path that was broken for six days.
2. Load `https://canvasdownloader.app/.well-known/security.txt` and confirm it
   serves.
3. In Search Console, resubmit the sitemap and use URL Inspection on anything
   new.
4. Re-run the mobile Core Web Vitals measurement against the live host, not a
   local copy: the CDN and the local server differ (4368 ms local against
   5300 ms live for the same page state).
