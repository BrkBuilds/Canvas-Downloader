# Changelog: what was built, changed and decided

Append a dated entry per working session. Newest first. This is the "what
exists now" record; [FINDINGS.md](FINDINGS.md) is the "why" record and carries
the evidence for everything below.

---

## 2026-08-26 - the login walkthrough left the homepage

The homepage carried the whole thing - **How to log in**, ~370 lines: the Canvas
URL card with the two address formats, the token card with its four steps and the
YouTube clip, the token-safety block, and a Setup Guide CTA. It sat directly under
the download buttons, so the first thing a visitor met after deciding to download
was a tutorial for a screen they cannot reach yet. The reasoning and the rule are
now a settled decision in [STRATEGY.md](STRATEGY.md).

### Where each piece went

| Piece | Now |
|---|---|
| Canvas URL + token walkthrough | `guide.html#api-token` - already there, already current (it named the institution picker and the *Get a token* button). Nothing had to be rewritten. |
| The 30-second clip | `guide.html`, same click-to-load `.guide-embed` pattern as `mac-setup.html`. Nothing is requested from YouTube until the play button is pressed - verified: 0 youtube/google requests on load. |
| *Your token is safe* + the does/doesn't lists | `index.html#security`, as a fifth full-width card in *Fair questions, straight answers*. |
| The Setup Guide CTA | Dropped. The nav's **How to set up** and the footer already carry it, and the post-download pages route there on their own. |

### The Windows gap this exposed

`mac-setup.html` has had a **Log in to Canvas** step since it was written;
`win-setup.html` had nothing. Removing the homepage section would have left a
Windows reader's whole path - homepage, `thanks-win.html`, `win-setup.html` -
saying not one word about the token. It now has a card **C**, three points, the
same length as the Mac one.

### Measured

| | Before | After |
|---|---|---|
| Homepage height, desktop 1280px | 11,399 px | **8,806 px** (-23%) |
| Homepage height, mobile 390px | 16,510 px | **12,585 px** (-3,925 px, -24%) |

On a phone that is close to four screens of scrolling removed from between the
download buttons and everything after them.

### Guards

`tests/test_website_login_claims.py` moved with the content, and all four changed
or new guards were run against a deliberately broken tree first - 4 of 4 caught:

- `test_the_homepage_does_not_teach_the_login` is new. It matches the Canvas
  **controls** a walkthrough has to name (*New Access Token*, *Generate Token*,
  *Get a token*, *Find your institution*), because the homepage legitimately says
  "token" many times and the breach card legitimately names *Approved
  Integrations* as the place to revoke one.
- `test_no_page_links_to_an_index_anchor_that_does_not_exist` became
  `..._a_local_anchor_...`. The narrow version only ever looked at `index.html`,
  so it could not see the `guide.html#api-token` link the setup pages now depend
  on - it would have passed on a dead link.
- The token-shown-once and named-button guards follow the content:
  `guide.html`, `win-setup.html`, `mac-setup.html`.

Also: the orphaned video-facade script was removed from `index.html`, the green
reassurance block got a `margin-top` (every card in that grid renders a **0px**
gap between summary and body - the other four read fine only because a text body
starts with its line box's own leading, which a bordered box does not get), and
`sitemap.xml` `lastmod` was bumped for the four edited pages.

---

## 2026-08-25 - the pillar demo videos, re-shot and re-cut

Four of the six homepage pillars got new recordings of the current UI. Two of
them were not videos before: **Daily Auto-Sync** was a static PNG, and
**Lecture Recordings** was a grid of four format icons that only restated the
checklist inside its own expander. Both now show the thing they describe
actually happening.

The full procedure, the encoding recipe and the reasoning behind each decision
are in **[PILLAR_VIDEOS.md](PILLAR_VIDEOS.md)**, which is new. This entry is
the what-changed; that file is the how-to.

### What is on the page now

| Pillar | Was | Now |
|---|---|---|
| 1. Download | video with a black margin baked in | re-cropped, edge to edge |
| 2. Quick Sync | old UI | `quick-sync-new-canvas-files.mp4` |
| 3. Daily Auto-Sync | **static PNG** | `daily-auto-sync-canvas-files.mp4` |
| 4. AI Optimization | old UI | `convert-canvas-files-for-ai.mp4` |
| 5. Sync Review | unchanged | unchanged |
| 6. Lecture Recordings | **four static icons** | `download-transcribe-panopto-lectures.mp4` |

All six autoplay and loop silently, as before. Every one now carries an
`aria-label`; the Today PNG's `alt` text was carried across rather than lost.

### The page got faster, not slower, and that took a second pass

The first pass regressed mobile LCP from **3476 to 3984 ms**. A `poster`
**cannot be lazy-loaded** - there is no `loading="lazy"` for one - so two more
videos meant two more images fetched eagerly in front of the hero image, which
is the LCP element. That is the same class of problem the 2026-08-20 deferred
video fix was built to solve, so it was not shipped.

Both the source and the poster now live in `data-` attributes and are attached
together by the existing IntersectionObserver. Attaching the poster with the
source loses nothing: its job is to cover the video download, not the scroll
approach, and at about 36 KB against a 1 to 2 MB clip it still wins by a wide
margin.

| | Before | After |
|---|---|---|
| Mobile LCP (390px, 4x CPU, 1.6 Mbps) | about 3480 ms | **2836 ms** |
| CLS | 0.0013 | 0.0013 |
| Posters and videos fetched on load | 4 | **0** |

CLS held only because every pillar video gained real `width`/`height`
attributes, including the two that were not otherwise touched. The poster used
to be what gave the element its intrinsic aspect ratio.

### Pillar 1 was a frame inside a frame

Reported by the operator, and it was real: the file was 1800x1440 with the
window at x 20-1779, y 24-1410, so about 20 to 25px of black was baked in. The
recording already carries its own Win11 rounded corners and shadow, so our
`border-radius` and `border` drew a second frame around the first one with
black in between. `cropdetect` does not find this: it only looks for pure
black, and the padding here is the window's own shadow.

Cropped to 1760x1388 and re-encoded at CRF 24 (SSIM 0.9990 against a
losslessly cropped copy). CRF 19 was tried first and rejected - it quadrupled
the file to 1031 KB faithfully preserving the original's own compression
artifacts, with no visible gain over 755 KB. The other five clips were
measured the same way and are all edge to edge.

### SEO

- Query-shaped filenames (`download-transcribe-panopto-lectures.mp4`), which
  are a ranking signal for video and image search.
- **Six `VideoObject` nodes** now, in page order, each with `width`, `height`
  and `duration` read out of `ffprobe`. Two added, three rewritten.
- Posters moved to **WebP at 1280 wide**, up from JPEG at 960. Measured on the
  same frame: **36 KB against 47 KB**, so larger for search and smaller on the
  wire. `thumbnailUrl` is unaffected by the poster being deferred, so the full
  search value is kept at zero render cost.
- Poster frames chosen and eyeballed per the rule already in `FINDINGS.md`. No
  file dialogs, no personal paths. Course names and codes are the existing,
  operator-owned status quo.

### Deliberately not done

- **AV1**, though it measured about 36% smaller at matched quality. It needs a
  codec fallback chain in the defer bridge, and a pillar video that fails to
  decode is worse than a larger one that always plays. The numbers are in
  `PILLAR_VIDEOS.md` section 6 if it is ever revisited.
- **A no-JS still.** Those visitors now see an empty slot where they saw a
  poster. It was already a dead video for them, since the source has been
  JS-gated since 2026-08-20. The obvious fix (`html:not(.js)` plus a
  `<noscript><img>`) collides with the old-WebKit path, which deliberately
  loads every clip eagerly: it would hide videos that are working.

### Files

`docs/index.html` (six video elements, the defer bridge, the `@graph`),
`docs/sitemap.xml` (`<lastmod>`), `docs/assets/` (+5 `.mp4`, +5 `.webp`
posters, -3 `.mp4`, -2 `.jpg` posters, -1 `.png`), and `marketing/`
(`PILLAR_VIDEOS.md` new, indexed from `README.md` and `SITE_RUNBOOK.md`).

Verified in a real browser: all six load, autoplay and loop (proved by seeking
to `duration - 0.4` and watching `currentTime` wrap), correct posters attached,
no leftover `data-*`, box heights identical before and after load, zero page
errors, zero 4xx, no horizontal overflow at 390px. 80 website tests pass.

---

## 2026-08-24 - the v2.0.2 Microsoft Store submission

**Submitted to Partner Center.** Certification pending; the live listing serves
v2.0.0 until it clears.

### Why the submission existed

Two of the three URL fields on the live listing were **404**, and had been since
the `birkls` -> `BrkBuilds` account rename. Both sides measured before submitting,
with the live values read out of the Store catalog API rather than off the
dashboard, so there is an exact before-shot to check against after publish:

| Field | Live listing, still serving | Submitted |
|---|---|---|
| Privacy policy | old Pages host, `/privacy.html` -> **404** | `canvasdownloader.app/privacy.html` -> **200** |
| Website | old Pages host, root -> **404** | `canvasdownloader.app/` -> **200** |
| Support | old owner's repo, `/issues` -> 200, because GitHub redirects a renamed *repository* for ever | the current repo, `/issues` -> **200** |

The exact dead strings are quoted in [FINDINGS.md](FINDINGS.md), which is
excluded from `tests/test_no_stale_repo_urls.py` precisely so it can hold them as
evidence. This file is **not** excluded and should stay that way: a changelog is
append-only and will outlive any one entry, so it names the hosts rather than
quoting them. That guard is also what caught a stray Store catalog dump left in
the repo root while this entry was being written.

### Submitted

- **Package v2.0.2.0** at rank 1, v2.0.0.0 left in place to be superseded
  automatically. Both submission-option checkboxes left unchecked: gradual
  rollout has no upside at this size, and the mandatory-update flag is UWP-only.
- **Eight new screenshots** replacing all nine v2.0.0 ones, each captioned.
- **Description, What's new, Product features and Keywords** rewritten.
- **Short description** filled. It IS a Partner Center field, under
  **Supplemental fields**, a section Partner Center collapses by default - which
  is why an earlier pass reported it missing.
- **Additional license terms** = the GitHub URL on its own, which is where the
  GPLv3 section 6 offer belongs and where Partner Center renders it clickable.
  **Copyright and trademark info** names the licence and carries the Instructure
  disclaimer.
- **Categories** Education > Study aids, with Productivity as a second category.
- **Privacy declaration** "Yes, my product uses personal information". That is
  the honest answer even for an app that uploads nothing: it *accesses* the
  user's Canvas token and course data. The privacy page carries a section headed
  "Information the app accesses", so a reviewer following the link finds the
  declaration explained rather than contradicted.

### Deferred deliberately

**16:9 super hero art and the trailer**, on a measurement rather than a guess -
see FINDINGS. A media-only follow-up submission touches no package, needs no
version bump and no copy review, and the live listing stays up through
certification.

One consequence acted on: with no hero and no trailer, **screenshot 1 is the
entire visual first impression**, which is what raises the stakes on the "On your
pc" capitalisation in that exact frame.

### Copy fact-checked against the source, not against the draft

Every checkable claim in the description was resolved in code. Correct as
written: five built-in presets, eight conversion toggles, 4,757 institutions
("4,750+"), the five Panopto outputs (`url`/`mp4`/`mp3`/`txt`/`srt`), the seven
secondary-content categories, and the five Sync Review categories, which map
one-to-one onto the labels the screen actually renders.

One false claim found and corrected, one omission flagged - both in FINDINGS.

### Verified by me vs reported by the owner

Worth separating, because only one half needs re-checking after publish.

**Verified:** the three URL fields on both sides (curl), the live listing's
current values (catalog API), the Properties page state, the hero/trailer
adoption survey, and the source checks above.

**Reported, not seen:** the final round of copy edits - the delete claim, Word
added to the conversions list, the `canvas` capitalisation, Panopto moved to
screenshot slot 4, the short-description swap, the keyword swap, the feature
split, and caption 1. The Store listing page was reviewed before those edits and
not after.

### After it goes live

Re-run the catalog command in [STORE_LISTING.md](STORE_LISTING.md) section 7.7.
The table above is the control, so a field that silently did not take shows up in
one command instead of in ten weeks.

---


## 2026-08-21 - social proof from the Store, and what the data changed

### Built

- **The adoption proof strip** in `docs/index.html`, between the hero and the
  "Hi, I'm Birk" card: **800+ installs / used by students in 100 countries /
  free and open source**. Floating tags, no background and no border, each over
  a dim green radial glow blurred so it has no edge; `space-between` so the row
  aligns with the card's left and right edges exactly (measured 214 and 1226 for
  both). Verified in a browser at every step, desktop and mobile, and with
  JavaScript disabled.
- **The retired `.trust-pill` CSS is gone**, replaced rather than joined.
- **`docs/llms.txt`** gained an `Adoption:` bullet with the same two figures.
  The top countries are named there and only there.
- No test enforces the adoption arithmetic, deliberately - a hard-coded ceiling
  on a growing, rounded-down figure is wrong the week after it is written
  (product owner, 2026-08-21). `tests/test_website_noscript_content.py` covers
  the part that does not rot: the strip stays visible without JavaScript.

### Measured

- Store dashboard to 2026-08-20: 767 successful installs, 99.21% install
  success, 6 uninstalls, 14.26K page views, **exactly 100 countries**.
- Store catalog API: **0 ratings, 0 reviews**; listing live 2026-06-11.
- GitHub release assets, all tags: **44 downloads**, so the Store is ~94% of
  installs.
- Without JavaScript: 75% of `index.html` and 97% of `guide.html` are invisible,
  `h1` included.

### Decided

- Publish downloads and country count only. Not engagement, not conversion, not
  "first time launches from Store" (which does not mean what it looks like).
- "Used by", never "loved by", while there are no reviews.
- **Round down, and no as-of date**: both figures are lifetime cumulative, so a
  rounded-down number can only understate. The dating rule stays for windowed
  figures.
- **Do not mention the absence of reviews.** An assistant builds a story from
  it, and the story is "unvetted, do not download".

### Corrected

- `STRATEGY.md`'s "overwhelmingly US" reading. It measured where tenants are,
  not where users are; the US is ~10% of installs.

---

## 2026-08-20 (later the same day) - clearing the deferred list

Everything below had been deferred in the entry beneath this one. Three of the
four are now done; the fourth is deferred again for a **better** reason.

### Done

- **`CLAUDE.md` pointer added** (line 779). It was blocked by a parallel session
  holding the file; the write was guarded by a read-compare so it could not
  clobber their edit. The bullet is not just a signpost: it carries the four
  facts from this folder that bite engineering rather than copy (advertise the
  shipped TAG not `version.py`; a `<button>` receiving a scripted `.href` is a
  dead control; `preload="none"` is ignored while `autoplay` is present; and
  student-facing copy says "Canvas", never "LMS").
- **`VideoObject` structured data + five poster frames.** Was blocked on
  thumbnails; ffmpeg was available, so it was unblocked rather than left. Real
  dimensions and durations read with `ffprobe`. Posters double as `poster=`
  attributes, which matters because the videos are deferred and the slot was
  otherwise blank until they loaded. **A personal name was legible in the first
  frame chosen for `Quick_Sync_Demo`** and the frames are now picked
  deliberately; see FINDINGS.md.
- **`docs/download-panopto-lecture-recordings.html`**, 1,561 words. Leads with
  the permission question because Panopto student downloads are off by default,
  and is bound to `DISCLAIMER.md` including the part where the app does not read
  the download-button setting.
- **`.github/REPO_SETUP.md` corrected.** Its "What does NOT break" section
  claimed old links keep working permanently. True of `github.com`, **false of
  the old GitHub Pages host**, which is why the release notes carry four hard
  404s. Added a "What DOES break, and step 6 cannot reach it" section, unblocked
  the social-preview to-do (the correctly sized file now exists), added the
  release-notes item, and pointed at `marketing/`.

### Deferred again, with a better reason

- **`canvas-to-notebooklm.html`.** It was going to be built on the premise that
  Office files must be converted because NotebookLM cannot read them. Checking
  found Google's own announcement (13 Nov 2025) adding **`.docx`** support, and
  no primary source confirming `.pptx` either way. The hook was false or about
  to become false, so the page was not written. FINDINGS.md records the durable
  framing to use instead.

### Not built, by the operator's own scope decision

- **In-app "rate on the Microsoft Store" prompt.** Still the highest-value
  remaining item, but the scope chosen on 2026-08-19 was "technical + content
  pages" and explicitly *not* the in-app growth option. It is a product change
  and should be asked for rather than assumed.

### Files added or changed in this pass

`CLAUDE.md`, `.github/REPO_SETUP.md`, `docs/index.html` (4 VideoObject nodes,
4 poster attributes), `docs/assets/poster-*.jpg` (5 new, 196 KB total),
`docs/download-panopto-lecture-recordings.html` (new),
`docs/sitemap.xml`, `docs/llms.txt`, every page's footer,
`scripts/guide_pages_content.py`, `tests/test_website_internal_links.py`
(new structured-data asset test), and this folder.

### Verification

- Full suite green. New structured-data test mutation-checked: deleting a
  poster is **caught**.
- Panopto page: 0px horizontal overflow at 390 / 768 / 1280, one `h1`, no false
  active nav item, no page errors, title 42 chars, description 165.
- Posters verified by eye on a contact sheet, then re-verified after
  re-picking the two risky frames.
- Every `VideoObject` `thumbnailUrl` and `contentUrl` resolves to a real file.

---

## 2026-08-20 - first SEO and marketing pass

Triggered by the question "what is missing SEO and marketing wise". Scope chosen
by the product owner: technical fixes plus content pages, no analytics script,
brand question postponed, off-site work delivered as documents with real links.

### Bugs found and fixed (none were SEO issues)

| What | Where | Live since |
|---|---|---|
| Both current-version download buttons did nothing | `docs/releases.html` | 2026-08-14 (6 days) |
| "Need the other version?" toggle rendered black on black | `docs/releases.html` | 2026-08-14 |
| All nine links on the 404 page returned 404 | `docs/404.html` | since the domain migration |
| Site advertised v2.0.2, which nobody could download | `docs/index.html` JSON-LD | unknown |
| Mobile LCP 5300 ms, Google's POOR band | `docs/index.html` | since the videos were added |
| Installer's publisher URL pointed at the pre-transfer owner | `Canvas_Downloader_Setup.iss` | since the org move |

### Files created

| Path | What |
|---|---|
| `marketing/` | This folder: README, FINDINGS, STRATEGY, SITE_RUNBOOK, PLAYBOOK, CHANGELOG |
| `docs/how-to-download-all-canvas-files.html` | 2,123 words. The money-query page. Generated. |
| `docs/canvas-access-after-graduation.html` | 1,452 words. Seasonal high-intent page. Generated. |
| `docs/llms.txt` | Factual brief for AI assistants |
| `docs/.well-known/security.txt` | RFC 9116, points at the existing SECURITY.md |
| `scripts/build_guide_pages.py` | Generator: lifts the shell from `win-setup.html`, adds article CSS and schema |
| `scripts/guide_pages_content.py` | The prose and page definitions for the two guide pages |
| `tests/test_website_download_links.py` | A scripted `.href` target must be an anchor; installers reachable without JS |
| `tests/test_website_advertises_shipped_version.py` | Every stated version equals the newest git tag |
| `tests/test_website_internal_links.py` | Internal links resolve; sitemap is complete and indexable |
| `tests/test_no_stale_repo_urls.py` | No links to the pre-transfer owner; installer URLs separate and absolute |

### Files changed

- **`docs/releases.html`** - rebuilt as static-first. Buttons back to anchors
  with real hrefs, version pills, size and date lines, static release history,
  JSON-LD, and a maintenance comment listing the six things to edit per release.
  The API-failure path now leaves the static content alone instead of replacing
  it with an error.
- **`docs/index.html`** - `softwareVersion` corrected to the shipped tag,
  `og:locale` to `en_US`, `theme-color` added, author identity unified to
  BrkBuilds with `sameAs`, `Person` and `FAQPage` (10 questions) nodes added,
  four demo videos deferred behind an IntersectionObserver, modal hardened to
  fall back to `data-src`, contextual links to the two new pages, footer links.
- **`docs/guide.html`** - `BreadcrumbList` + `FAQPage` (13 questions) + `WebSite`.
- **`docs/engine.html`** - `BreadcrumbList` + `TechArticle` + `Person` + `SoftwareApplication`.
- **`docs/win-setup.html`, `mac-setup.html`, `privacy.html`, `disclaimer.html`** -
  `BreadcrumbList`, `theme-color`, footer links. `mac-setup.html` also defers its
  install video (934 KB saved while the collapsed full guide stays closed).
- **`docs/404.html`** - all nine paths made root-relative.
- **`docs/sitemap.xml`** - two new URLs, all `lastmod` refreshed.
- **`docs/thanks-win.html`, `thanks-mac.html`** - footer links only.
- **`Canvas_Downloader_Setup.iss`** - three separate absolute URLs replacing one
  with appended suffixes; `AppComments` dropped "LMS" per the vocabulary rule.

### Measured results

| | Before | After |
|---|---|---|
| Mobile LCP (390px, 4x CPU, 1.6 Mbps) | 5300 ms live / 4368 ms local | **2764 ms** |
| Mobile CLS | 0.0219 | **0.0013** |
| Desktop LCP | 276 ms | 212 ms |
| Media requests before scroll | 4 | **0** |
| Pages with structured data | 1 of 13 | **10 of 13** |
| Crawlable installer links on `/releases.html` | 0 | **4** |
| Pages with dangling `@id` references | 4 | **0** |
| Site content words | ~19,900 | **23,400** |

### Verification performed

- Full suite: **3,889 passed, 17 skipped**.
- Mutation pass on the new tests: **10 of 10 caught**.
- Architecture audit: **PASS**, 0 violations.
- All 13 pages: exactly one `h1`, no broken internal links, no dangling schema
  references, all JSON-LD parses.
- Every outbound link on the site checked: all resolve.
- Both new pages checked for horizontal overflow at 360, 390, 768, 1180, 1600.
- Video playback and the click-to-expand modal verified unchanged against the
  unmodified pages, per video, scrolled into view one at a time.
- Both `releases.html` download buttons verified to start real file transfers,
  with the GitHub API both reachable and blocked.

### Decisions taken (detail in STRATEGY.md)

- Vocabulary: **"Canvas", never "LMS"** in anything a student reads.
- **No analytics script.** Search Console and Bing Webmaster only.
- **Brand question postponed**, with the owner's reasoning recorded.
- **English first**, on the 1,330-US-against-9-Danish institution measurement.
- **Do not add width/height to ~200 images**; measured CLS does not justify it.

### Left deliberately undone

1. In-app "rate on the Microsoft Store" prompt (highest-value remaining).
2. `download-panopto-lecture-recordings.html` and `canvas-to-notebooklm.html`.
3. `VideoObject` schema, blocked on generating poster thumbnails.
4. Five operator-only actions, listed in `PLAYBOOK.md` section 1b.

### Not done because another session held the file

`CLAUDE.md` was being edited concurrently by a parallel session, so nothing was
appended to it, per this repo's own rule about shared documents. **It still
needs a pointer to this folder.** Suggested line for its audit-memory section:

> **Marketing, SEO and launch memory lives in `marketing/`** (README, FINDINGS,
> STRATEGY, SITE_RUNBOOK, PLAYBOOK, CHANGELOG). Same rule as the audit
> documents: anything durable about the website, search visibility or the
> launch goes there, in the same commit as the change, written mechanism-first.
