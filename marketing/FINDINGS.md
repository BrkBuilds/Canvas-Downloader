# Findings register: website, SEO and launch

Every defect and opportunity found, what proved it, and what happened to it.
Written mechanism-first: what breaks, how it was measured, and why the obvious
fix is wrong. Statuses are `fixed`, `deferred`, `open`, `settled` or `invalid`.

Anything `deferred` carries the reason. Anything `settled` is a decision, and
lives in [STRATEGY.md](STRATEGY.md) as well.

**Session of 2026-08-20** produced everything below unless stated otherwise.

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

## OPEN: is the site indexed at all?

**Status: open. This is the most important unanswered question in this folder.**

Three web searches, one containing the literal string `canvasdownloader.app`,
returned **zero** results from the domain. The Microsoft Store listing appeared
in two of them, and a search assistant summarising the product **quoted the
Store copy**.

That evidence is consistent with two very different situations, and they need
opposite responses:

- **not indexed** (a technical or trust problem: fix crawling, request indexing);
- **indexed and ranking nowhere** (an authority problem: the answer is off-site
  work, which is `PLAYBOOK.md`).

Scripted `site:` queries against Bing and DuckDuckGo were attempted and are
**not reliable evidence**: both block scripted access, and a control query
(`site:instructure.com`) returned zero results through the same parser, proving
the parser, not the index. Do not repeat that approach.

**Google Search Console answers it definitively, under Pages.** The verification
meta tag is already on the homepage.

## OPEN / operator-only: five things that cannot be done from the repo

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

## DEFERRED: `canvas-to-notebooklm.html`

**Status: deferred, and the reason changed on investigation. Read this before
building it.**

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
