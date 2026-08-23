# Findings register: website, SEO and launch

Every defect and opportunity found, what proved it, and what happened to it.
Written mechanism-first: what breaks, how it was measured, and why the obvious
fix is wrong. Statuses are `fixed`, `deferred`, `open`, `settled` or `invalid`.

Anything `deferred` carries the reason. Anything `settled` is a decision, and
lives in [STRATEGY.md](STRATEGY.md) as well.

**Session of 2026-08-20** produced everything below unless stated otherwise.

---

## FIXED: the site had no social proof, while the Store had the only traction

**Status: fixed 2026-08-21.** `docs/index.html` and `docs/llms.txt`.

Three tags sit between the hero and the "Hi, I'm Birk" card: **800+ installs**,
**used by students in 100 countries**, and **free and open source**. The same
facts are in `llms.txt`, which is where an assistant reads them.

**Measured 2026-08-20 from the Microsoft Store Partner Center dashboard**, plus
two live API checks:

| | |
|---|---|
| Page views | 14.26K |
| Installs | 750 tile / **767 funnel "Successful installs"** / 764 in the geographical spread |
| Install success rate | **99.21%** (6 failures; the 62 user aborts are excluded) |
| User-initiated uninstalls | 6, i.e. 0.8% of installs |
| Conversion | 5.26% |
| Countries | **exactly 100**, 764 installs attributed. PH 82, US 79, AU 70, ZA 62, IN 55, NG 27, GB 24, NZ 23, BR 22, then a long tail: 46 countries have 1 or 2 |
| GitHub release assets, all tags | **44 downloads** (16 + 14 + 3 + 11) |
| Store ratings and reviews | **0 and 0** |
| Store listing live since | 2026-06-11 |
| Monthly active devices | 39 average, 236 on 2.0.0.0, 764 sessions (opt-in telemetry only) |

Two of those reframe everything else, and both are cheap to repeat:

1. **The Store has ZERO ratings and zero reviews.** Store catalog API,
   `storeedgefd.dsx.mp.microsoft.com/v9.0/products/9n1dwwvrq5wc`:
   `AverageRating = 0.0`, `RatingCount = 0`. So this data is **usage proof, not
   opinion proof**. There are no stars to show, no quotes to pull, and **no
   honest `aggregateRating` to put in JSON-LD** - which is now a test.
2. **The Store is ~94% of all installs** (~97% for Windows). So Store numbers
   can stand in for total adoption without hand-waving, and pushing people to
   the Store is also what makes reviews possible.

### The published figures, and exactly what each is

- **800+ installs.** The Store dashboard reported the install half three ways
  on 2026-08-20 (750 tile / 764 geographical / 767 funnel), plus 44 GitHub
  release-asset downloads. **Growth outruns the snapshot**: at the observed
  ~120 installs a week the real number moved past 800 within days, which is why
  the page is deliberately rounded down and carries no as-of date.

  **DECIDED (product owner, 2026-08-21): the word on the page is "installs" and
  the exact arithmetic is not worth policing.** An earlier pass argued
  "downloads" was the more defensible umbrella for a combined figure and briefly
  changed the page; that was reverted. The figure is a rounded-down floor on a
  number that only goes up, so the pedantry bought nothing and the tests written
  to enforce it were brittle by construction - any hard-coded ceiling is wrong
  the week after it is written. Do not re-open this.
- **100 countries**, not "97 more countries" beside three named ones. The names
  were dropped from the page by the product owner: the count is the point, and
  naming three of a hundred makes the row long without making it truer. The
  names stay in `llms.txt` only, because an assistant gets asked "is it used in
  <country>" and a web page does not.

### No as-of date, and why that is correct here rather than sloppy

The first version dated the figure ("750+ installs since June 2026") on the rule
that an undated number rots. The product owner removed the date, and on
inspection the rule did not apply: **both figures are LIFETIME CUMULATIVE, so
they can only go up.** A figure rounded DOWN can therefore only ever understate,
which is the safe direction, and "since June 2026" was decoration that also made
the sentence longer. **The dating rule still stands for any WINDOWED
figure**, which is what it was written for - it simply does not apply to a
cumulative one.

### The look: floating, not chips

Restyled the same day. The tags carry **no background and no border**; each is
its icon and its words over a soft radial glow drawn on `::before`, blurred so
it has no edge. The page already has a bordered card immediately below the row,
and a second set of bordered boxes above it read as clutter.

- **The glow is green** (the icons' own `--green`), dim, and blurred. A blue one
  was tried and read as too bright against the navy page.
- **A `radial-gradient` glow does not stretch with a long tag.** With
  `ellipse closest-side` the bright core is a central blob and the outer stops
  are too faint to see, so on a wide tag the light sat in the middle and stopped
  well short of the words. It was briefly replaced with a horizontal
  `linear-gradient`, then reverted when the middle tag was shortened, which
  removed the problem at its source. If a long tag is ever needed again, the
  linear form is the fix, not a stronger radial one.
- **CORRECTED 2026-08-21: the shipped rule is `justify-content: center`, not
  `space-between`, and the 214/1226 figures are the CONTAINER's edges, not tag
  ink.** This entry described a variant that is not in `docs/index.html`.
  Re-measured in Chromium against the real page at three widths - strip box vs
  persona-card box: `1440px [214,1226]` vs `[214,1226]`; `1280px [134,1146]` vs
  `[134,1146]`; `900px [24,876]` vs `[24,876]`. The boxes align **exactly** at
  every width and the tags sit centred inside, inset 143/155/101px
  symmetrically. What makes the row track the card is that it is a full-width
  flex row with no width or max-width of its own - the distribution keyword is
  a design choice on top of that, and packing the tags LEFT is the only variant
  that would end short of the card's right edge.
  What makes it track the card is that it is a full-width flex row with no width
  of its own; the distribution keyword is a design choice on top of that.
- The band sits `18px` below the hero and `44px` above the card, deliberately
  closer to the hero. **The bottom margin has to beat the card's own inline
  `margin-top: 20px` outright**: adjacent block siblings collapse to the larger
  of the two, so anything under 20px there does nothing at all.

### What was deliberately NOT published, and why

- **Engagement.** 39 monthly active devices, 0.79 min average session, DAD/MAD
  1.10%, week-2 cohort retention mostly 0 to 15%. Weak, opt-in only, and it
  would undercut the sync story. Arguably expected for a download-and-go tool,
  but see the open engineering question below.
- **"First time launches from Store" (296 against 767 installs).** Ambiguous: it
  counts launches started *from the Store app*, not from the Start Menu, so it
  is **not** "61% never opened it". Do not build copy on it.
- **Conversion (5.26%).** Meaningless to a visitor and it invites comparison.
- **99.21% install success**, and the 6 uninstalls. Both strong, both
  defensible; the product owner narrowed the published set to downloads plus
  geography, so they live here and in nothing that ships. They are the obvious
  candidates if the strip ever gains a fourth tag.
- **"Loved by".** Offered and declined: with zero reviews, nothing on the site
  may claim how users feel about it. "Used by" is measured.
- **The absence of reviews.** Named in `llms.txt` in the first version and
  removed by the product owner, on the reasoning that **an assistant latches on
  to a fact like that and builds a story from it** - most likely "it has no
  reviews, so it may not be safe to download". Omission is both true and safer.
  There is now a test for it, because the instinct to disclose is strong.

### The rules that keep these numbers honest

The site has no build step, no analytics and inlines everything per page, so a
hand-written number can drift in one page and nothing would say so.

- **Round DOWN, always.** It is the whole reason no date is needed.
- **One figure, by hand.** `docs/index.html` and `docs/llms.txt` are the only
  two surfaces that state it; change them together. There is deliberately NO
  test enforcing the arithmetic - see the decision above. The rules that DO
  matter and are worth keeping in your head: no rating markup anywhere (the
  Store has 0 ratings and 0 reviews, so there is nothing honest to put in an
  `aggregateRating`, and search engines render that markup as stars); never
  mention the absence of reviews; say "used by", not "loved by"; and keep the
  strip OUT of a `.reveal` so a non-rendering crawler can still see it -
  `tests/test_website_noscript_content.py` covers that last one.

### Four traps paid for while building it

- **`docs/llms.txt` is LF; every `.html` page is CRLF.** A patch written with
  `\r\n` for both fails on one of them.
- **A hard-wrapped file breaks phrase matching.** The first dated-claim test
  failed against perfectly correct copy because `llms.txt` wraps at ~80 columns
  and "June 2026" straddled a line break. Normalise whitespace before matching.
- **A token can survive inside a CSS comment.** The mutant
  `background: none; /* was: radial-gradient(...` left the word the glow test
  looked for sitting in a comment, and the test passed against a strip with no
  glow at all. `_css()` now strips CSS comments, for the same reason `_text()`
  strips HTML ones. Found by the mutation pass, not by review.
- **`justify-content: space-between;` occurs three times in `index.html`**, so
  the mutant for the alignment rule rewrote an unrelated block and the strip was
  never touched. That reads as a missing test and is not one. Anchor on the
  preceding line.

### The retired `.trust-pill` CSS is gone

It had had no markup using it for some time. A test now fails on any `.proof-`
rule nothing uses, so the same corpse cannot form again.

---

## FIXED: 75% of the homepage and 97% of the guide were invisible without JavaScript

**Status: fixed 2026-08-21, verified on the deployed site.** This entry still
read `open` on 2026-08-23, two days after the fix shipped. The register was
wrong, not the site, and a stale `open` is the expensive direction: it invites a
second session to re-investigate something already done.

The fix is the inversion described below, and it is live on all three pages
(`html:not(.js) .reveal { opacity: 1; transform: none; }` in `index.html`,
`guide.html` and `engine.html`), guarded by
`tests/test_website_noscript_content.py`, and measured at **0 hidden words** on
`index` and `guide`, against 3,125 and 7,025 before. The JS path was controlled
against the deployed pre-fix site: identical reveal count, identical hidden
count, identical per-element delay ladder, identical computed transition.

The finding as originally written follows, because the mechanism is worth
keeping.

Nearly every block on the homepage carries `class="reveal"`, which is
`opacity: 0` until an IntersectionObserver adds `.vis`. There is **no
`<noscript>` fallback anywhere on the site**. Measured with a real parser, words
inside a `.reveal` as a share of each page's body text:

| Page | Hidden without JS | `h1` hidden |
|---|---|---|
| `guide.html` | **7,025 / 7,217 (97%)** | yes |
| `index.html` | **3,125 / 4,112 (75%)** | yes |
| `engine.html` | 59 / 3,491 (1%) | **yes** |
| the three generated guide pages | 0% | no |

Confirmed visually: a `java_script_enabled=False` render of the homepage hero is
a **blank dark rectangle** with nothing in it but the new proof strip, which was
deliberately left out of a `.reveal` for exactly this reason.

**Why this matters more than it looks.** Google renders JavaScript, so Google is
probably unaffected. Several assistant crawlers do not. This folder already
records that the site "appeared in zero of three web searches" and that "when a
search assistant summarised the product it quoted the Store copy, not the site".
A homepage whose `h1` and three quarters of whose text are `opacity: 0` to a
non-rendering fetch is a plausible contributing cause, and the two worst pages
are the two that carry the content.

**The fix is an inversion, not a rewrite.** Hide only when scripting is present:

```css
html.js .reveal { opacity: 0; transform: translateY(20px); }
```

plus one line at the top of `<head>`:

```html
<script>document.documentElement.className += ' js';</script>
```

With JS the animation is byte-for-byte what it is today; without JS nothing is
hidden. It is three pages (`index`, `guide`, `engine`) and it must be verified
in a browser on each, because `.reveal` also carries the stagger delay the
observer applies.

**Do not "fix" it by deleting `.reveal`.** The animation is part of the page's
design and the operator has tuned around it.

---

## CORRECTED: the market is not "overwhelmingly US"

**Status: corrected 2026-08-21. Supersedes the basis, not the conclusion.**

`STRATEGY.md` said the audience is "most likely in the United States",
**measured** from the app's own institution directory: 1,330 US institutions
against 9 Danish. That was a measurement of *where Canvas tenants are*, not of
*where users are*, and the Store dashboard now answers the second question
directly:

| Country | Store installs | Institutions in the picker with a known country |
|---|---|---|
| Philippines | 82 (#1) | 13 |
| United States | 79 (#2) | 1,330 |
| Australia | 70 (#3) | 33 |
| South Africa | 62 (#4) | **2** |
| India | 55 (#5) | **4** |
| Nigeria | 27 (#6) | **0** |
| United Kingdom | 24 (#7) | 31 |

Right-hand column counted from `shared/institutions.py` (4,757 rows, 3,199 with
no known country). The operator notes the geography has **shifted since it was
last checked**, so this is drift rather than an error at the time.

**English first is untouched and if anything stronger** - every country in that
list is English-speaking. What changes is the picture of who the reader is: the
US is 10% of installs, not the overwhelming majority, and copy or examples that
assume a US student are speaking to one visitor in ten.

**The engineering consequence is the bigger half.** Four of the top six install
countries are among the worst covered in the picker's opening state, which shows
"institutions in your country" and falls back to the curated seeds below five
rows. A Nigerian student gets the fallback. `CLAUDE.md` already records that the
crawl finds many Philippine and Indian tenants that are dropped for want of
evidence of ownership; this says that is exactly where the users are. Filed for
engineering, not for marketing.

---

## RESTATED: the in-app "rate on the Store" prompt is still the highest-value item

**Status: still deferred, and now with a measured zero behind it.**

The Store listing has **0 ratings and 0 reviews** after 750 installs and ten
weeks (API-verified above). Store ranking is driven by ratings and installs, and
the Store listing is the only surface of this product that ranks. Everything in
the entry further down this file stands; this adds the number.

Note the ordering that follows from it: the website can cite installs today, but
it cannot cite an opinion until this exists. That is the gap, not the copy.

---

## FIXED: the two download buttons on `/releases.html` did nothing

**Status: fixed.** Broken 2026-08-14, found and fixed 2026-08-20. Six days live.

Commit `31dd133` ("website audit and fixes to be 1-1 w app") converted three
`<a href="#">` elements into `<button type="button">`. That is correct for a
JavaScript control, and the OS toggle got its `addEventListener` and kept
working. It is wrong for a navigation: the release script still ran

    el('win-exe').href = winAsset.browser_download_url;

and assigning `.href` to an `HTMLButtonElement` creates a meaningless expando
property. Neither element had a click handler. **Clicking "Download direct
(.exe)" or "Download for macOS (.dmg)" produced no navigation and no download.**

**How it was proved**, because reading the DOM spec is not evidence: the real
GitHub API payload was stubbed into the page with Playwright so the page's own
success path ran, then the buttons were clicked. `url changed = False`,
`download started = False` for both. The **control** in the same run is what
makes it conclusive: the *older* releases below them, built by `makeAsset()` as
genuine `<a>` elements, downloaded normally. So the newest build was the only
one a visitor could not get.

**A false lead worth recording.** The first probe showed the page rendering its
"Couldn't reach GitHub right now" error state, which looked like a second bug.
It was the sandbox blocking `api.github.com`; the API answers 200 with
`Access-Control-Allow-Origin: *`. Stubbing the payload is what separated the
environment artifact from the real defect. Do not report a JS-dependent page as
broken without that separation.

Fixed by converting both back to `<a>` with real static `href`s.
Guarded by `tests/test_website_download_links.py`, which asserts the general
rule (nothing that receives a scripted `.href` may be a non-anchor), not just
these two ids.

## FIXED: the OS toggle was invisible

**Status: fixed.** Same commit `31dd133`, same cause, third casualty.

`#toggle-os-btn` became a `<button>`, and the stylesheet said `.os-toggle a`.
The rule silently stopped matching. **A `<button>` does not inherit `color` from
`body`**, so it fell back to the UA default: black text on a near-black page.

Fixed by matching both tags, with a comment saying why the colour declaration is
load-bearing rather than decorative.

## FIXED: `/releases.html` was invisible to crawlers

**Status: fixed.**

The highest-intent page on the site (sitemap priority 0.9, in the nav and footer
of every page) rendered, to anything that does not run JavaScript, as the words
**"Loading the latest release..."**. Version numbers, download URLs, sizes,
dates and the release history were all injected client-side from
`api.github.com`. Content words: **166**.

Now static-first: every one of those facts is in the HTML, and the script
overwrites them when GitHub answers. Content words: **194** (this figure was
first reported as 420, which was wrong because the count included the new HTML
comment; the honest gain is 166 to 194 words plus **0 to 4 crawlable installer
links** and 0 to 2 static version numbers).

**The failure mode was also inverted.** The old page replaced working markup
with an error message when the API failed. It now leaves the correct static
content alone. A visitor behind a firewall that blocks `api.github.com` used to
get an error instead of a download; they now get the download.

The page carries a maintenance comment listing the six things to edit per
release. See [SITE_RUNBOOK.md](SITE_RUNBOOK.md).

## FIXED: every link on the 404 page was dead

**Status: fixed.**

`docs/404.html` still used the GitHub Pages *project* paths from before commit
`8a277be` moved the site to canvasdownloader.app: `/Canvas-Downloader/releases.html`
and eight others. Verified against the live host: **all nine returned 404**,
including the page's own `fonts.css` and favicon.

So the one page whose entire job is rescuing a visitor who already hit a dead
URL offered them four more dead URLs and rendered without its font.

It survived the domain migration because **nobody visits the 404 page on
purpose**. Nothing links to it, so no click-through reveals it, and it is
correctly excluded from the sitemap.

Fixed with root-relative paths. **They must be root-relative**: a 404 is served
for a URL at any depth, so `guide.html` would resolve against whatever bogus
directory the visitor typed. Guarded by `tests/test_website_internal_links.py`.

## FIXED: the site advertised a version nobody could download

**Status: fixed.**

The homepage `SoftwareApplication` JSON-LD said `softwareVersion: 2.0.2`. The
newest shipped tag was **v2.0.1**.

The cause is a correct rule applied to the wrong place. `version.py` is
*deliberately* kept ahead of every shipped tag, which is what
`tests/test_version_leads_tags.py` enforces, because the in-app update banner
compares the newest GitHub tag against the running build. So `version.py` is the
right source for the app and the **wrong** source for anything user-facing on
the website. The website must advertise what a visitor can actually obtain,
which is the newest **tag**.

Guarded by `tests/test_website_advertises_shipped_version.py`, which pins every
place the site states a version (both pills, both `Version X.Y.Z` lines, both
download URLs, and `softwareVersion` in two pages' JSON-LD) to the newest tag,
and skips rather than fails when tags are not visible.

## FIXED: structured data existed on one page out of thirteen

**Status: fixed.**

Only `index.html` carried JSON-LD (`WebSite` + `SoftwareApplication`). The 33
question-and-answer pairs already written across the site were invisible to
machines, and no page declared breadcrumbs, an author or an article.

Now on 10 of 13 pages (the three excluded are `404` and the two `noindex`
download-confirmation pages, correctly): `FAQPage` over the existing 10 homepage
and 13 guide questions, `TechArticle` on `engine.html`, `Article` on both new
guide pages, `BreadcrumbList` everywhere, plus `Person`, `WebSite` and
release-specific `SoftwareApplication`.

**Answers in schema are the visible text with tags stripped, never a rewrite.**
Structured data that does not match what the page says is the one way this
markup can hurt instead of help.

**Honest note on value:** Google restricted FAQ rich results to authoritative
government and health sites in 2023, and deprecated HowTo results. So the FAQ
markup is not a rich-snippet play. It is worth doing for AI answer engines and
Bing, which parse it, and that is the whole of the claim.

## FIXED: four pages carried dangling `@id` references

**Status: fixed.** Introduced by me earlier the same session, caught by writing
a validator instead of trusting that the JSON parsed.

`author`, `publisher` and `isPartOf` were written as bare `{"@id": ".../#author"}`
references to nodes that existed only on `index.html`. **Google resolves the
graph per page, not per site**, so those pages declared an author with no name.

Fixed by defining `Person`, `WebSite` and `SoftwareApplication` nodes on every
page that references them. A validator now checks reference resolution and
required properties per type, not merely that the JSON parses.

## FIXED: mobile Core Web Vitals were in Google's POOR band

**Status: fixed.** The most consequential finding of the session, and it was
missed on the first pass by measuring the wrong thing.

**The mistake first.** The initial audit measured desktop, unthrottled: LCP
1068 ms, CLS 0.0057, and reported "performance is not your problem". Core Web
Vitals are **field data, predominantly mobile**. On a 390px profile at 4x CPU
throttle and 1.6 Mbps, the live site measured **LCP 5300 ms**, which is POOR
(the threshold is 4000 ms).

**The cause, measured by request order.** The four demo `.mp4` files were
requested at positions **6, 7, 8 and 9** - immediately behind the hero image and
before it finished. The LCP element *is* that hero image
(`CanvasDownloaderHero.webp`, 178 KB). 4.7 MB of below-the-fold video, which
nobody had scrolled to, was saturating the connection and starving the one
element that decides the score.

**Two candidates were A/B'd on a local server under identical throttling:**

| | LCP | CLS | media requests before scroll |
|---|---|---|---|
| baseline | 4368 ms | 0.0219 | 4 |
| `preload="none"` | 4320 ms | 0.0219 | **4** |
| defer the `src` | **2764 ms** | **0.0013** | **0** |

**`preload="none"` DOES NOT WORK, and this is the reusable fact.** The browser
ignores it while the `autoplay` attribute is present. It was measured first
precisely because it is the obvious fix, and it changed nothing within noise.
Withholding the `src` until an IntersectionObserver says the video is near the
viewport is what works: **-1604 ms LCP, CLS down 94%**.

**Behaviour verified unchanged**, not assumed: each video scrolled into view
reports `paused: false`, `readyState: 4` and an advancing `currentTime`,
identical to the baseline, and the click-to-expand modal still opens with the
correct source. The modal was hardened to fall back to `data-src`, because it
read `v.src` and a deferred video has none.

**A trap this created on `mac-setup.html`.** Its video lives inside a **closed
`<details class="full-guide">`**. Testing it by calling `scrollIntoView` reports
the video as still deferred, which reads as a broken fix. It is correct:
an element inside a collapsed disclosure has no layout and genuinely does not
intersect. Opening the disclosure loads and plays it immediately. Measured:
guide closed, **0 media requests** (934 KB saved for everyone who never opens
it); guide opened, loads and plays. The comment in that file says all of this,
because the next person to test it will otherwise "fix" a working feature.

## FIXED: a table stretched the whole page sideways on mobile

**Status: fixed.** Introduced by me, found by measuring at five viewport widths.

The comparison table on the new guide page declares `min-width: 640px` so its
columns stay readable. On a 390px phone the **whole page** scrolled sideways,
with 172 elements past the viewport edge.

**The mechanism:** the site's shell makes `<body>` a **column flex container**,
so `.container` is a flex item and its width is the *cross* size. With
`width: auto` that size is resolved from content, and the table's `min-width`
propagated all the way up: the container came out **688px** on a 390px viewport.

**`min-width: 0` was tried first and measured no different.** The fix is
`width: 100%` on the container: a definite width stops the content-based sizing,
the container lands at 342px, and the wrapper's own `overflow-x` then does its
job. Verified 0px page overflow at 360, 390, 768, 1180 and 1600.

## FIXED: the installer carried a third spelling of the old repo URL

**Status: fixed.**

`Canvas_Downloader_Setup.iss` had
`#define AppURL "https://github.com/birkls/canvas-downloader"`. That is the
publisher URL Windows shows in Apps & features for every installed copy.

`scripts/migrate_repo_urls.py` ran on 2026-08-19 for the move to the BrkBuilds
organisation and did its job well. It substitutes two exact strings:
`birkls/Canvas_LMS_batch_file_downloader`, then any remaining bare
`Canvas_LMS_batch_file_downloader`. This line is a **third spelling** (old owner,
lowercase hyphenated repo) that matched neither, so it survived silently.

Nothing was broken for users, because GitHub 301-redirects a renamed owner.
**That redirect is exactly why it rots quietly, and it is not permanent: a
released GitHub username can be claimed by anyone**, at which point a URL baked
into a shipped installer resolves to a stranger's account.

**A defect I introduced fixing it.** Pointing `AppURL` at the website silently
broke two more, because lines below built `AppSupportURL={#AppURL}/issues` and
`AppUpdatesURL={#AppURL}/releases`. Those were correct only while `AppURL`
happened to be the GitHub repo; they became `canvasdownloader.app//issues`.
Caught by checking my own change rather than assuming it. All three are now
separate absolute URLs, and `tests/test_no_stale_repo_urls.py` forbids the
concatenation pattern as well as scanning for the old owner.

## FIXED: smaller things, batched

- **`og:locale` was `en`**, which is not the spec format (`language_TERRITORY`).
  Now `en_US`.
- **No `theme-color`** anywhere, so mobile Chrome painted its bar white above a
  near-black page. Added sitewide.
- **Author identity was split**: JSON-LD said `birkls` / `github.com/birkls`
  while the repo, the Microsoft Store publisher and Ko-fi all say `BrkBuilds`.
  Unified, with `sameAs` linking the profiles.
- **The nav marked the wrong item active** on both new pages, because the shell
  was lifted verbatim from `win-setup.html`. It told every visitor to a guide
  page that they were on the setup page. Introduced by me; fixed in the
  generator so it cannot recur.
- **Titles and descriptions over length** on both new pages (63 and 67 chars;
  176 and 187 chars). Both now 58 to 59 and 148.
- **The scrollable comparison table** had no keyboard or screen-reader
  affordance. Now `tabindex="0"`, `role="region"` and an `aria-label`.
- **`AppComments` in the installer said "Canvas LMS"**, which is administrator
  vocabulary. See the vocabulary rule in [STRATEGY.md](STRATEGY.md).

## BUILT: a blog index, and the footer stopped being a list of articles

**Status: built 2026-08-23.** `docs/blog.html`, generated from `PAGES`.

Three article links sat loose in the footer of fourteen hand-maintained pages.
That is a list of articles pretending to be navigation, and its cost is
structural rather than cosmetic: **every new article was fourteen edits**, each
page inlines its own footer, and nothing tells you when one is missed. It also
caps the content strategy at however many links look reasonable in a footer,
which is about three.

There is now one **Blog** entry pointing at an index that is DERIVED from the
same `PAGES` list the articles are built from - titles, dates, descriptions and
a reading time computed from the body. Adding a dict is the whole job.

Schema is `CollectionPage` + `ItemList` rather than `Blog` + `BlogPosting`,
deliberately: each article already declares an `Article` node at `<url>#article`,
and a second typed node for the same URL declared from a different page is how
two competing descriptions of one document end up in the index. An `ItemList`
only points. Article breadcrumbs gained a Blog rung at the same time, because a
breadcrumb that skips a real level describes a structure the visitor cannot
navigate.

Verified in a browser before shipping: all five cards resolve 200, zero
horizontal overflow at 360 / 390 / 768 / 1180 / 1600, no page errors, and the
whole index and both new articles render fully with **JavaScript disabled**.

## BUILT: two more search-facing pages

**Status: built 2026-08-23**, taking the set to five.

- **`save-canvas-assignment-feedback.html`.** The load-bearing fact was found
  during grounding and reframed the page: Canvas **does** have a one-click
  student export of submissions (Account > Settings > Download Submissions), and
  it contains none of the feedback - no annotations, no comments, no rubrics, no
  grades - and it expires after 30 days. So the page is not "how to download
  your work", it is "Canvas gives you your half and not theirs". The product
  mention is honest about the limit: the app saves grade, rubric, comment thread
  and comment attachments, and does **not** capture DocViewer annotations,
  because those are drawn in the viewer rather than stored on the file.
- **`canvas-files-into-notebooklm.html`.** See the NotebookLM entry below.

Both were grounded against sources before a word was written, and the facts that
shaped them are recorded in the `guide_pages_content.py` docstring beside the
prose, per this project's usual rule.

## FIXED: two search-facing pages now exist

**Status: fixed (built).** See [SITE_RUNBOOK.md](SITE_RUNBOOK.md) for how to
edit or add more.

Every pre-existing page documented the *product*. Nothing answered the question
a student types. `docs/how-to-download-all-canvas-files.html` (2,123 words) and
`docs/canvas-access-after-graduation.html` (1,452 words) do.

Both are fact-checked against primary sources, and the research corrected the
copy twice: **students cannot export a course** (`.imscc` export is an
instructor permission), and **the submissions export excludes
instructor-annotated versions**. Both are common misconceptions and both are now
stated on the page.

Also created: `docs/llms.txt` (a factual brief for AI assistants) and
`docs/.well-known/security.txt` (RFC 9116, pointing at the existing
`SECURITY.md`).

---

## ANSWERED: the site IS indexed, and already carries an AI Overview

**Status: answered 2026-08-23**, from Search Console and a signed-in browser.
This was the most important unanswered question in this folder, and the answer
is the good one.

Three pieces of evidence, and it takes all three:

- **`site:canvasdownloader.app` in a signed-in browser** returns the homepage
  plus `guide`, `releases`, `engine`, `disclaimer`, `privacy` and `win-setup`,
  each with a real title and a real snippet. The homepage snippet is dated
  "2 days ago", so the crawler is not merely aware of the site, it is coming
  back.
- **Google renders an AI Overview for the brand query, and it is built from OUR
  copy** - "a free, open-source tool that lets you batch-download course files,
  readings, and lecture media" - with `privacy.html` surfaced as a source card
  beside the Store listing. The observation this folder was founded on, that an
  assistant summarised the product from the Store copy rather than from the
  site, **no longer holds**.
- **Search Console**: `sitemap.xml` submitted 19 Aug, last read 22 Aug, status
  Success, **11 pages discovered**. HTTPS 8 valid, 0 non-HTTPS. Breadcrumbs 4
  valid, 0 invalid. Videos 4 valid, 0 invalid.

**So the constraint was never crawling.** Of the two branches below it is the
second: indexed, and ranking for a brand term nobody searches. That makes
`PLAYBOOK.md` - off-site work, links, directories, communities - the entire
remaining lever, and it retires the technical branch completely. Do not spend
another hour on crawlability.

### The Pages report, once it finished processing

Read 2026-08-23, before the blog changes were deployed: **8 indexed, 5 not
indexed across 3 reasons.** Every row was then opened, so the URLs below are
observed and not inferred.

**The four non-issues, confirmed by URL:**

| Reason | URLs | Verdict |
|---|---|---|
| Page with redirect | `http://www`, `https://www`, `http://` apex | Correct. All three 301 to the canonical apex, measured independently. The property is a DOMAIN property, so it includes every variant, and three is exactly how many exist |
| Alternate page with proper canonical | `/index.html` | Correct. GitHub Pages serves it 200 and its canonical points at `/`, so Google indexed `/` and filed the duplicate |

Every canonical on the site was audited alongside: **17 pages, all
self-referencing, none claimed twice**, and the only three without one
(`404.html`, both `thanks-*`) are all `noindex`.

### THE ACTUAL FINDING: not one search-facing page is indexed

The eight indexed URLs are `/`, `guide`, `engine`, `releases`, `win-setup`,
`mac-setup`, `privacy` and `disclaimer` - **every one of them a product page,
and every one of them old.** Of the three pages written specifically to rank:

- `download-panopto-lecture-recordings.html` - **crawled 21 Aug, not indexed**
- `how-to-download-all-canvas-files.html` - **absent from the report entirely**
- `canvas-access-after-graduation.html` - **absent from the report entirely**

Absent is not the same as rejected: it means Google has not crawled them at all.
So the honest summary is that the site's SEO content has **zero index presence**,
which is worth stating plainly because the headline "8 indexed" reads like
success and the eight are the pages that were never the point.

**Do not over-read it yet, for two measured reasons.** The pages were published
20 Aug and this report's data ends 21 Aug, so they are one to three days old.
And all three not-indexed categories are stamped *"first detected 22.08.2026"*,
i.e. the property itself is days old and this is its first crawl report - there
is no history here and no trend to read.

**The plausible mechanism, and it is the one thing that was ours to fix.**
Before 2026-08-23 the ONLY internal links to those three pages were in the
FOOTER. Sitewide boilerplate links are the weakest internal signal there is,
and they were competing with a dozen other footer links on every page. There
was no hub, no contextual link, and nothing telling Google those three pages
were a category rather than three loose files.

That is exactly what the blog index changes: `/blog.html` is a real hub with
one card per article, descriptive anchor text, and body links between the
articles themselves. **This is the strongest on-site lever available for this
precise symptom** - which is a happy accident of timing, since the blog was
built for maintainability rather than for this.

**It is a discovery and crawl fix, NOT an authority fix, and the distinction
decides what to do next.** If `download-panopto-lecture-recordings.html` is
still crawled-not-indexed a few weeks after the blog is live and has been
submitted, then internal linking has done all it can and the answer is off-site:
`PLAYBOOK.md`, not more pages and not more markup.

**Core Web Vitals shows "no data" rather than a score, and that is not a
regression.** CWV in Search Console is FIELD data from real Chrome users, and
the site does not have the traffic for a significant sample. The lab numbers in
this folder (mobile LCP 2764 ms, CLS 0.0013) remain the only measurements that
exist and remain valid. Its emptiness is a traffic fact, not a performance fact.

**Expect the numbers to look WORSE right after the blog deploy, and do not read
that as a regression.** Three new URLs will be discovered before they are
crawled, so a "Discovered - currently not indexed" bucket will appear and the
not-indexed count will rise for a week or two. That is the normal shape of
publishing.

**The old lesson stands and is worth keeping.** Scripted `site:` queries against
Bing and DuckDuckGo are NOT reliable evidence: both block scripted access, and a
control query (`site:instructure.com`) returned zero through the same parser,
proving the parser and not the index. What settled this was a signed-in human
browser plus Search Console, which is what should settle it next time.

## MOSTLY DONE / operator-only: what is left of the five

**Status updated 2026-08-23.** Items 1, 4 and 5 are **done**; item 2 turned out
to be a different and worse defect and now has its own entry below; item 3 is
the only one still untouched. The original list is kept whole rather than
trimmed, so nobody re-derives it.

| # | Item | State |
|---|---|---|
| 1 | v2.0.1 release-note dead links | **done** 2026-08-21, across v2.0.1, v2.0.0 and v1.0.0, each replacement verified 200 before publishing |
| 2 | GitHub social preview | **not "unset" - BROKEN.** See the entry below |
| 3 | Bing Webmaster Tools | **open**, and now the only untouched one |
| 4 | Search Console | **done** - property verified, sitemap submitted and read, and it answered the indexing question above |
| 5 | GitHub Discussions | **done**, enabled 2026-08-21 |

Full detail and exact replacement text in `PLAYBOOK.md` section 1b.

1. **The v2.0.1 release notes carry five dead links.** Four
   `birkls.github.io/Canvas_LMS_batch_file_downloader/...` URLs, including the
   headline "Website & guides" link, plus one stale `github.com/birkls/...`.
   The github.com one redirects; **the `github.io` ones do not**, because a
   project Pages site stops existing when you move to a custom domain. The
   migration script could not touch these because release notes live on GitHub,
   not in the tree. v2.0.0 and v1.0.0 have stale links too.
   The notes also name the Windows asset `Canvas_Downloader_Setup_2.0.1.exe`
   while the attached file is `Canvas_Downloader_v2.0.1_Windows.exe`.
2. **The GitHub social preview is not set.**
   `docs/assets/github-social-preview.png` exists at exactly the right size
   (1280x640, verified) and the API reports no custom Open Graph image, so every
   shared repo link renders a generic auto-card.
3. **Bing Webmaster Tools is not set up.** One-click import from Search Console.
   Feeds Bing, DuckDuckGo and Copilot, which matters more than Bing's market
   share because several AI assistants are Bing-backed.
4. **Search Console**: submit the sitemap, request indexing for the three new
   guide pages, and answer the open question above.
5. **GitHub Discussions is off.** Enabling it creates indexable Q&A on a
   high-authority domain that links back to the site.

## OPEN / yours: the GitHub social preview is SET and points at a DELETED image

**Status: diagnosed 2026-08-23. The repair is two clicks and it is yours -
there is no REST API for this field.**

This supersedes two earlier and both-wrong readings of the same thing. The
register first said the preview was **not set**; `CLAUDE.md` corrected that to
**set, but it is the 1024x1024 app icon on a surface that renders 2:1**. Neither
was right, and the correction was as wrong as the original.

**Measured**, which is the only reason the truth came out. The repo page carries:

```
og:image = https://repository-images.githubusercontent.com/1136287256/7ae23d37-...
```

That is the **custom-upload** host; an auto-generated card would be
`opengraph.githubassets.com`. So GitHub does hold a custom-preview record. And
that exact URL answers:

```
HTTP/1.1 404 The requested content does not exist.
x-ms-error-code: WebContentNotFound
```

**The record exists and the image behind it does not.** One fact, every symptom:
the Settings box renders as an empty rectangle because it is displaying a 404,
an upload appears "not to show up", and every shared link resolves its card
image to nothing. The likely cause is the move from `birkls` to the `BrkBuilds`
organisation, which can orphan the blob while leaving the reference behind, and
that is also why re-uploading over it does not help.

**The repair, and the order matters:** Settings > General > Social preview >
**Edit > Remove image FIRST**, so the dangling record is cleared, and only then
upload `docs/assets/github-social-preview.png`. Uploading without removing is
what has already been tried.

**How to verify it, since the Settings box cannot be trusted to show it.** One
command, and it is the check to repeat after any future repo move or rename:

```bash
curl -s https://github.com/BrkBuilds/Canvas-Downloader \
  | grep -oE '<meta property="og:image"[^>]*>'      # read the URL
curl -sI "<that url>" | head -1                     # must be 200, not 404
```

`200` with `Content-Type: image/png` is the pass. Pasting the repo link into a
Slack or Discord message box is the visual confirmation.

The correct asset is in the repo and verified at exactly **1280x640**
(`docs/assets/github-social-preview.png`, 384,637 bytes). `docs/icon.png` is
1024x1024 and is **not** the file to upload here.

## FIXED: four VideoObject nodes carried an invalid `uploadDate`

**Status: fixed 2026-08-23**, `docs/index.html`, guarded by
`tests/test_website_internal_links.py`
(`test_every_videoobject_uploaddate_carries_a_timezone`).

Search Console reported two issues against all four VideoObject nodes on
22 Aug: *"Datetime property 'uploadDate' is missing a timezone"* and *"Invalid
datetime value for 'uploadDate'"*. The value was a bare `2026-08-14`.
schema.org accepts a plain Date; **Google's VideoObject documentation requires
an ISO 8601 datetime**, and a date-only value satisfies neither warning. It is
now `2026-08-14T00:00:00+00:00`.

**Both warnings are non-critical today** - the items stay valid and eligible -
and Google's own notice says non-critical issues *can be reclassified as
critical later*, at which point the video rich result disappears with no change
on our side. So this is cheap insurance, not a live bug, and it is worth
recording as such rather than inflating it.

**It is guarded because it is invisible.** No page renders `uploadDate`, no
existing test parsed it, and its only audience is a crawler - which reports the
problem weeks later, by email, in whatever language the Search Console account
happens to be set to. The guard has a positive control (it fails on the old
value, verified) and a floor assertion (`seen >= 4`) so it cannot pass vacuously
the day those nodes are renamed or dropped.

**Deliberately NOT widened.** The first version checked every schema datetime
and found bare `datePublished` / `dateModified` on Article nodes across five
pages. Those are fine: Google's article guidance recommends a timezone but
accepts a date, and Search Console has never flagged one. Widening would mean
eleven edits to satisfy a requirement that does not exist, and a test stricter
than its own spec teaches the next person to distrust it.

## ACCEPTED: one video is "not on a watch page", so it will not be indexed

**Status: accepted 2026-08-23. Not a defect, and not worth fixing.**

Search Console's Video indexing report: **1 video not indexed, 0 indexed**,
reason *"Video is not on a watch page"*. Google indexes a video when it is the
main content of its own page; these are short UI demos embedded in a marketing
page, so the classification is correct.

Fixing it means a dedicated page per video whose primary content is that video.
That is four thin pages, and `STRATEGY.md` already settles the general case:
**two strong pages beat eight thin ones, and thin pages actively hurt.** The
VideoObject markup still earns its place - it is what can produce a video
thumbnail beside an ordinary result - so nothing is removed.

## DEFERRED: in-app "rate on the Microsoft Store" prompt

**Status: deferred. Highest-value remaining item.**

Microsoft Store ranking is driven by ratings and installs, and the Store listing
is currently the only surface of this product that ranks. There is no in-app
prompt to rate.

Deferred because it touches the completion screens, which in this codebase have
strict container-inheritance rules (`CLAUDE.md`: "A keyed card can be INHERITED
by the next element", "A container inherits the previous run's CHILDREN"). A
section whose element count changes with state shifts every element after it.
It needs its own before-and-after browser pass, not a hurried one.

Design constraints when it is built: show it once, only after a genuinely
successful run, never after a cancelled or failed one, and never twice.

## FIXED: the Panopto page

**Status: fixed 2026-08-20.** `docs/download-panopto-lecture-recordings.html`,
1,561 words.

A distinct, high-volume query the product genuinely serves, and the one page on
this site capable of causing a reader real harm if written carelessly. It
therefore **leads with the permission question and not with capability**.

Facts verified before writing, and they shaped the whole structure: **Panopto
student downloads are OFF by default.** Only the recording's creator and
administrators can download unless a Creator changes the setting, which they can
do per folder, per subfolder or per recording. When it is enabled, viewers get a
download option under the three-dots menu; when it is not, no button appears at
all. Sources: Stanford Canvas Help 360047508074, Cambridge UIS lecture-capture
guidance, Bryn Mawr Ask Athena, Shoreline KB 2026.

So the page's honest order is: check for the button, then **ask your lecturer**
(with a drafted request, because two clicks in folder settings is the answer that
actually works), then your institution's policy, and only then the app.

**The copy is bound to `DISCLAIMER.md` and must stay bound to it.** The
disclaimer states plainly that the app performs the same LTI handshake a browser
performs, saves the same stream the player would send, breaks no encryption, and
**does not read the download-button setting**. The page says exactly that,
including the last part, and repeats the disclaimer's three cautions. Any future
edit that makes this read as a workaround misrepresents the product.

## BUILT: the NotebookLM page, on a corrected premise

**Status: built 2026-08-23 as `canvas-files-into-notebooklm.html`.** The
deferral below was right to happen and its reasoning is what made the page
worth writing: re-grounded on 2026-08-23, Word and PowerPoint support are both
confirmed, so the original hook was retired rather than repeated.

What the page is framed on instead, all of it durable: **NotebookLM cannot
reach Canvas at all**, so everything has to be a local file first; the source
cap makes curation the real skill and pushes one notebook per course; and
**local video is not an accepted source type while audio is**, which is the one
place a conversion step is genuinely still required. Current figures are stated
as current, not as permanent: 50 sources per notebook on the free plan, 500,000
words or 200 MB per source.

The original deferral note follows, because its lesson - do not build a page on
a fact that a vendor ships changes to monthly - is the reusable part.

## DEFERRED (superseded by the above): `canvas-to-notebooklm.html`

**Status: superseded. Read this before writing anything else about NotebookLM.**

The page was going to be built on the premise that Office files must be
converted to PDF because NotebookLM cannot read them. **That premise is at least
partly false as of 2026.** Google's own announcement (13 November 2025) confirms
NotebookLM added support for **Microsoft Word `.docx`**, along with Google
Sheets, Drive URLs, images and Drive PDFs. A third-party source also claims
`.pptx` is supported; **that could not be confirmed from a primary source**, so
neither claim should be made.

The load-bearing facts here are volatile: Google ships changes to NotebookLM
monthly, and a page whose hook is "NotebookLM cannot read X" is wrong the moment
that changes. Deferred rather than shipped on facts that could not be verified.

**If it is built, frame it on what does not change:** NotebookLM cannot reach
your Canvas courses at all, so the files have to be local first; free notebooks
cap sources per notebook (50 on free at the time of checking), so *what* you
upload matters; and a lecture video is far more useful to it as audio or a
transcript than as an MP4. None of those depend on a format list.

## FIXED: `VideoObject` structured data, and poster frames

**Status: fixed 2026-08-20 (was deferred, then unblocked).**

The four demo videos were unexploited for video search. `VideoObject` requires a
`thumbnailUrl` and no poster images existed. ffmpeg was available, so five
posters were generated (196 KB total), wired in as `poster=` attributes and
declared in the homepage graph with each video's **real** width, height and
duration read from `ffprobe`. Schema that misstates a duration is worse than no
schema.

The `poster` attribute is worth as much as the markup: the videos are deferred
until the visitor approaches them, so without a poster the slot was blank until
the video loaded.

**A privacy finding came out of picking the frames, and it is the reusable
part.** The first pass took a frame from 15% into each video. For
`Quick_Sync_Demo` that landed on a Windows file dialog whose OneDrive sidebar
showed **a legible personal name**, plus Danish personal folder names. The video
containing that frame is already public and autoplays on the homepage, so the
poster exposed nothing new - but a `thumbnailUrl` **actively submits an image
for indexing**, which is broader and more persistent than a frame inside a
looping video. `.github/REPO_SETUP.md` already flags the same class of question
for the README screenshots.

Frames are therefore **chosen, not sampled at a fixed percentage**:
`Quick_Sync_Demo` at 35% (the app's own sync screen) and
`DownloadAllCourses_Folders` at 92% (the fullest grid of course folders, which is
the product's promise in one picture). **Re-check any regenerated poster by eye
before shipping it.**

**Still the operator's call:** the posters show real CBS course names and codes.
That is institutional rather than personal, and it is already visible in the
videos and screenshots, but it is the same decision `REPO_SETUP.md` defers on.

Guarded by `test_every_same_origin_url_in_structured_data_resolves`, because a
`thumbnailUrl` pointing at a deleted file produces no visible symptom and no
console error: the only audience that sees it is the one that cannot report it.

## SETTLED: the brand-name collision, postponed by the operator

**Status: settled as postponed. Do not reopen without new evidence.**

The name is contested: `canvasdownloader.com` is a **Spotify Canvas**
downloader, plus three Chrome extensions and five GitHub repos share the name.

Three responses were proposed on 2026-08-19 and **all were rejected by the
product owner**, with two corrections that are now standing rules:

1. **"Canvas LMS" is not the disambiguator.** Students say "Canvas". "LMS" is
   administrator vocabulary and reads as noise to the audience. See
   [STRATEGY.md](STRATEGY.md).
2. **The Spotify collision does not need solving.** In the owner's judgement, a
   user looking to download files from Canvas will filter out the Spotify result
   and take the second one. Ranking second on a polluted term is acceptable.

Revisit only with data (for example Search Console showing brand-query
impressions with no clicks).

## SETTLED: no analytics script

**Status: settled 2026-08-19 by the product owner.**

Search Console and Bing Webmaster only. No on-page script of any kind.

The consequence is accepted and should not be re-argued: **the funnel below the
click is invisible**. There is no way to know which page drives a download.
Proxies available instead: Search Console impressions per page, GitHub release
download counts (already on the README badge), and the Microsoft Store
dashboard's install numbers.

If this is ever revisited, `docs/privacy.html` must change in the same commit or
the site is making a false claim.

## SETTLED: English first, no localisation

**Status: settled on measurement, 2026-08-19.**

An instinct to localise for the Danish market was **wrong and was dropped after
checking the app's own verified institution list**: 1,330 institutions with a
known country are US against **9 Danish**, plus 3,199 `.instructure.com` tenants
that are predominantly US.

## SETTLED: do not add width and height to the site's images

**Status: settled on measurement.**

Roughly 200 images lack explicit dimensions, which is normally a Cumulative
Layout Shift risk. **Measured CLS is 0.0057 on desktop and 0.0013 on mobile**,
against a "good" threshold of 0.1. The CSS already constrains them. Editing 200
image tags would be churn with no measurable benefit.

---

## Verified facts about Canvas, with sources

Checked 2026-08-20 against primary sources. Reused in the guide pages; recheck
before relying on them in new copy.

- **"Download as Zip"** from a course's Files tab, after `Ctrl`/`Cmd`+`A`:
  University of Illinois KB 127046, Stanford Canvas Help 115001602467,
  NCTC 205334770.
- **Files under Account > Files > Submissions are the student's OWN uploads**,
  not the course material. Illinois KB 127046 describes exactly this and it is
  easy to mistake for a course-file export.
- The thorough submissions route is **Account > Settings > Download Submissions
  > Create Export**, and it covers concluded courses.
- **The submissions export excludes instructor-annotated versions** and carries
  no grades or feedback comments.
- **Nothing in Canvas exports Pages or Assignments in bulk.** The accepted
  answer on Instructure Community discussion 618390 (Oct 2024) says: *"As for
  Pages and Assignments, I'm not sure of a quick way off the top of my head."*
- **Students cannot export a course.** The `.imscc` export is an instructor
  permission (Instructure Community discussion 633259, Feb 2025, asker tagged
  Instructor).
- **Studio media downloads one at a time** (same thread, second accepted answer).
- **Some institutions disable student access-token generation.** Source: the
  asker in discussion 618390, *"my school has recently removed that feature"*.
  This is why the token caveat is stated plainly on the comparison page rather
  than buried.
