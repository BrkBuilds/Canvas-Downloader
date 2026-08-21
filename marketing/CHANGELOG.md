# Changelog: what was built, changed and decided

Append a dated entry per working session. Newest first. This is the "what
exists now" record; [FINDINGS.md](FINDINGS.md) is the "why" record and carries
the evidence for everything below.

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
