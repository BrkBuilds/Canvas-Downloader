# Search Console and Bing Webmaster: first real read (2026-08-27)

Written from the exports and URL inspections in `marketing/search-data/` (which is
gitignored, so the raw data is local-only), plus live probes of
the deployed site. **Merge into `marketing/FINDINGS.md`** when the parallel
session releases that file; it is kept separate only to avoid clobbering
concurrent edits.

The property is 8 days old and GSC lags 2 to 3 days, so every figure below ends
**24 Aug** unless stated. Indexing data is signal at this age; ranking data is
mostly noise, with one exception noted.

---

## ANSWERED: the 2026-08-23 open question. It was discovery, and the blog fixed it

`FINDINGS.md` recorded *"not one search-facing page is indexed"* and predicted
that if the pages were still unindexed a few weeks after the blog hub shipped,
the answer would be off-site. **That prediction came true four days early, with
better evidence than the test it proposed.**

| Page | Verdict (27 Aug) | Last crawl | Google's stated referrer |
|---|---|---|---|
| `blog.html` | **Indexed** | crawled | none reported |
| `canvas-access-after-graduation.html` | **Indexed** | 25 Aug 03:20 | `https://canvasdownloader.app/` |
| `save-canvas-assignment-feedback.html` | **Indexed** | 24 Aug 01:46 | none reported |
| `download-panopto-lecture-recordings.html` | Crawled, not indexed | **21 Aug 18:41** | `win-setup.html` |
| `how-to-download-all-canvas-files.html` | **Unknown to Google** | never | none |
| `canvas-files-into-notebooklm.html` | **Unknown to Google** | never | none |

Three of the six are indexed, against zero on 23 Aug. The blog hub was the only
intervening change.

---

## THE ACTUAL FINDING: crawl budget, and internal links cannot buy more of it

`how-to-download-all-canvas-files.html` has been live since **20 Aug 13:25**
(commit `0a17bdb`), carries **9 internal links from 7 pages**, sits in the
sitemap at priority 0.9, and Google has never fetched it. Every site-side cause
was ruled out by measurement:

| Check | Result |
|---|---|
| HTTP status | `200`, `text/html; charset=utf-8` |
| `X-Robots-Tag` | none |
| `<meta name="robots">` | none |
| Canonical | self-referencing, correct |
| In live sitemap | yes, `priority 0.9`, `lastmod 2026-08-20` |
| Sitemap read by Google | 26 Aug, Success, 14 URLs |
| Anchors | real `<a href>` in raw HTML, none in `<noscript>` |

**Two proofs close it.**

**1. The adjacency proof.** Both of these links sit in the *same paragraph* on
the homepage, and have since 23 Aug 22:44 (`git log -S` on `docs/index.html`):

> Still deciding how to get your courses off Canvas? Read
> **[every way to download your Canvas files, compared]**, or, if you are
> finishing your degree,
> **[what happens to your Canvas access after graduation]**.

Google names `https://canvasdownloader.app/` as the **referring page** for
`canvas-access-after-graduation`, crawled 25 Aug 03:20 and indexed. So Googlebot
parsed that exact paragraph, followed the *second* anchor, and did not fetch the
*first*. Discovery is not the problem; scheduling is.

**2. The A/B proof.** `save-canvas-assignment-feedback` and
`canvas-files-into-notebooklm` were published in the **same commit** (`494a420`,
23 Aug 22:44), with identical headers and identical linking (one body link each,
both from `blog.html`).

- feedback: crawled **24 Aug 01:46**, about three hours later, indexed.
- notebooklm: **never crawled.**

No site variable differs. Google is choosing.

### Internal link count is ANTI-correlated with outcome here

| Page | Internal body links | Outcome |
|---|---|---|
| `how-to-download-all-canvas-files` | **9** | never crawled |
| `canvas-access-after-graduation` | 5 | indexed |
| `download-panopto-lecture-recordings` | 3 | crawled, not indexed |
| `save-canvas-assignment-feedback` | 1 | **indexed** |
| `canvas-files-into-notebooklm` | 1 | never crawled |

**So "add more internal links" is dead as a diagnosis**, and adding more
articles does not help either: publishing divides the same small budget rather
than enlarging it. On-site work is done. The remaining levers are Request
Indexing (used), IndexNow (now wired, below) and external authority.

`blog.html` is reachable from **footer boilerplate only** (14 footer links, 0
body links). Putting Blog in the nav would breach the settled four-item nav
decision, so that is a product-owner call rather than an obvious fix. Given the
anti-correlation above, expect little from it.

---

## The performance data is better than the indexing data suggests

**Correction to an earlier read in this session:** the Insights screen said
*"no clicks for this period"*, and that was taken at face value. The Performance
export contradicts it. **There are 2 clicks.** Insights was the wrong instrument.

| Date | Clicks | Impressions | Avg position |
|---|---|---|---|
| 19 Aug | 0 | 1 | 1 |
| 21 Aug | 0 | 4 | 19.5 |
| 22 Aug | 0 | 11 | 12.8 |
| 23 Aug | 0 | 18 | 6.0 |
| **24 Aug** | **2** | **65** | 14.9 |

Impressions 1 → 4 → 11 → 18 → 65. First clicks on 24 Aug.

**Queries (all 7 that exist):**

| Query | Impressions | Position |
|---|---|---|
| `canvas downloader` | 20 | **6.05** |
| `canvas course downloader` | 3 | 8 |
| `can you access canvas after graduation` | 2 | 6.5 |
| `how long do you have access to canvas after graduation` | 1 | 9 |
| `canvas files downloader` | 1 | 11 |
| `do i have access to course content in canvas after graduation qut` | 1 | 11 |
| `how to install canvas` | 1 | 54 |

**Pages:** homepage 34 impressions (pos 9.76, 1 click);
`canvas-access-after-graduation.html` **30 impressions, pos 7.77, 1 click**.

Two things follow, and both matter:

- **The long-tail content strategy in `STRATEGY.md` section 4 is working.** Four
  of seven queries are informational graduation-access phrases, and the one
  indexed article is pulling nearly as many impressions as the entire homepage,
  at a better position, within three days of being indexed.
- **This QUANTIFIES the cost of the crawl problem.** One indexed article is
  worth ~30 impressions in three days. Two uncrawled articles are worth zero.
  The `qut` in one query is Queensland University of Technology, matching
  Australia as a top-5 impression country.

The brand term `canvas downloader` sits at **position 6.05**, i.e. page one, on
a phrase `STRATEGY.md` records as contested. The brand-name question was
postponed pending exactly this data.

---

## FIXED: IndexNow was hosting a key and never submitting

Bing's IndexNow page kept showing its setup screen. The key file was correct and
live all along:

```
https://canvasdownloader.app/2b07a6c59aed473f8be3319d97848444.txt
  200, text/plain, body == the key
```

**Hosting the key is only half of IndexNow.** Bing activates on the first
successful *submission*, and nothing in this repo ever submitted: no script, no
workflow, no ping. The feature had been inert since the key was generated.

Now `scripts/ping_indexnow.py` plus `.github/workflows/indexnow.yml`:

- **The key is DERIVED, never restated.** `find_key()` globs `docs/` for the
  hex-named `.txt` whose content equals its own stem. Hardcoding it would be a
  second copy of one fact, which this repo has been bitten by three times
  (`make_long_path`'s duplicate, the three AppleScript escapers, the six-site
  module-item scope rule).
- **Only changed pages are submitted** (`--changed-since`), because
  re-announcing an unchanged set every push is what receiving engines treat as
  noise. `--all` is the explicit exception for activation and manual resubmits.
- **A liveness check drops anything not answering 200**, and it earned its keep
  on the first run: the working tree's sitemap listed **5 pages that 404**
  (`download-lecture-videos-from-canvas`, `panopto-lecture-transcript`,
  `save-canvas-pages-quizzes-discussions`, `canvas-access-token-explained`,
  `canvas-download-tools-compared`), all written but not yet deployed.
  Announcing a 404 is worse than announcing nothing.
- **`--wait-seconds` exists for CI only.** A push fires the workflow immediately
  but GitHub Pages takes time to publish, so a freshly-committed page is briefly
  absent for a reason that resolves itself. A bounded wait tells that apart from
  a page that is genuinely missing, without ever blocking forever.
- **A rejection exits non-zero.** A ping that silently no-ops is the exact state
  this replaced.

**First submission: `IndexNow accepted 14 URL(s): HTTP 200`.** Both ref
fallbacks (all-zeros from a new branch, and a SHA absent from the checkout) were
tested and degrade to `HEAD~1` rather than crashing.

---

## Ruled out, with evidence. Do not chase these

- **`blog.html` "2/3 page resources could not be loaded"** (the woff2 and
  `icon.png`). Both return `200` with correct content types, and the font
  serves `Access-Control-Allow-Origin: *`, so the `crossorigin` preload is
  valid. This is Googlebot declining to re-fetch, not a defect.
- **Bing Site Scan's 3 "Alt attribute for images is missing" warnings** on `/`,
  `engine.html`, `guide.html`. Every `<img>` on all three has an `alt`
  (35/58/71 tags, zero missing). They are `alt=""`, which is the **correct**
  WCAG treatment for decorative icons; Bing's checker does not distinguish empty
  from absent. "Fixing" it would make screen readers announce 57 decorative icon
  names on `engine.html`, which is strictly worse for the users the attribute
  serves.
- **"The homepage has no meta description."** This was raised in-session and
  **was a false finding**, disproved before it reached the register. The tag is
  present at 124 characters; its attributes are split across a line break, which
  defeated a line-based grep. Recorded because this file's own rule is that a
  finding's stated mechanism is a hypothesis until tested.
- **Core Web Vitals "not enough data".** A traffic fact, not a performance fact.
  The lab figures already in `FINDINGS.md` remain the only valid ones.

---

## Open, and what would close it

- **GSC Links report** was still processing (`Dataene behandles`). Bing reported
  **0 referring domains**. Note this is a *measurement*, not a fact about the
  world: the operator has links from a dev YouTube channel, the Microsoft Store,
  Reddit, and pending listings on Softpedia, Product Hunt and AlternativeTo.
  Worth knowing when they do appear: YouTube-description, Reddit and Store links
  are `nofollow`, so they drive discovery and crawl demand but pass little
  ranking signal, whereas directory listings usually pass some. Both help here,
  for different reasons.
- **`download-panopto-lecture-recordings`** has not been re-crawled since 21
  Aug, two days *before* the blog hub existed, so it has never been reassessed
  with the current link graph. Request Indexing was used on 27 Aug.
- **Bing Keyword Research** has not been run with real phrases. It is the only
  free source of absolute search volume available to this project, and
  `BLOG_PLAN.md` decides page count on *measured* demand.
- **Bing AI Performance (BETA)** has not been read. That is the Copilot and
  ChatGPT surface, i.e. the one `docs/llms.txt` was written for.

## Deploy hazard for whoever pushes next

`docs/sitemap.xml` in the working tree lists **5 URLs that currently 404**. The
deployed sitemap has 14 and is clean. Pushing the sitemap without the article
files submits five 404s to both engines. The IndexNow script now refuses to
announce them, but the sitemap itself carries no such guard.

---

# Second pass, same day (27 Aug, 04:40): four live probes

Everything below was measured against a live endpoint, not read off a
dashboard or inferred from a record. Three of the four close an item that this
register had open.

## FIXED: the GitHub social preview. GitHub repaired it after escalation

`FINDINGS.md` recorded this as *"RESOLVED as far as it can be"* with the
`opengraph.githubassets.com` fallback as the expected pass, because uploads were
accepted while the blob 404'd and there is no REST API for the field. The
operator escalated with the evidence in that entry. **GitHub fixed the storage
state, and the upload now takes.**

Verified with the exact two-step check that entry prescribes, because reading the
tag is not enough and this register has twice been wrong by doing only that:

```
og:image  https://repository-images.githubusercontent.com/1136287256/96475500-d8ba-49b2-ab8f-7c444f24e5f0
          HTTP/1.1 200 OK
          384,637 bytes, PNG, 1280x640
```

`repository-images.githubusercontent.com` + 200 is the entry's stated condition
for *"the custom image is finally working"*, and 1280x640 is GitHub's own
recommended size. **The escalation text in `FINDINGS.md` worked and is worth
keeping** as the template for the next time a GitHub field is broken with no
self-service route: it named the three orphaned record ids, showed that the
remove path worked while the write path did not, and gave the repo id and the
transfer history.

Right-size the win the same way the original entry does: it affects the card
when the repo link is pasted into Slack, Discord, X or iMessage. It touches
nothing about indexing, the Store or the site's own OG image.

## LIVE: the Store's Privacy Policy and Website links

The 2026-08-24 submission has published. Read from the catalog API, which is the
control that entry set up so a fix that silently did not take is visible in one
command:

| Field | Was | Now |
|---|---|---|
| `PrivacyUrl` | `birkls.github.io/...` -> 404 | `canvasdownloader.app/privacy.html` -> **200** |
| `AppWebsiteUrl` | `birkls.github.io/...` -> 404 | `canvasdownloader.app/` -> **200** |

That closes the item at the top of `FINDINGS.md` and clears the Store Policy
10.5.1 exposure. `RatingCount` is still **0**, which is the next section.

## MEASURED: the Store keyword set is HALF working, and the failures share one property

The 2026-08-24 measurement asked for a re-run in about two weeks. Run at three
days instead, because the question turned out to be answerable early.

| Query | 24 Aug | **27 Aug** |
|---|---|---|
| `canvas downloader` | #1 | **#1** |
| `canvas course` | #8 | **#1** |
| `canvas sync` | not measured | **#1** |
| `canvas course downloader` | not measured | **#1** |
| `download course files` | not in top 20 | **#7** |
| `download canvas files` | not measured | **#9** |
| `bulk course download` | not in top 20 | **#10** |
| `panopto downloader` | not measured | **#13** |
| `panopto lecture recordings` | not measured | **not in top 20** |
| `notebooklm study files` | not measured | **not in top 20** |
| `lecture transcripts subtitles` | not measured | **not in top 20** |
| `panopto` / `notebooklm` / `lecture downloader` | not in top 20 | **not in top 20** |
| `canvas lms` | not in top 20 | **not in top 20** |

**The first four rows are the control, and without them this measurement means
nothing.** `canvas course` moving #8 -> #1 and `download course files` going from
absent to #7 proves the keyword submission has been indexed. So the bottom rows
are not "too early to tell"; they are the same index answering no.

**The pattern is exact. Every query that ranks contains `canvas`, `course` or
`downloader`. Every query that does not rank contains none of them - including
the three keyword phrases sitting in the field verbatim.**

Three of the seven keyword slots in `STORE_LISTING.md` section 3.6 are therefore
producing nothing measurable:

```
panopto lecture recordings      <- no rank on the phrase, or on `panopto`
notebooklm study files          <- no rank on the phrase, or on `notebooklm`
lecture transcripts subtitles   <- no rank on the phrase
```

**This sharpens the 2026-08-24 conclusion rather than contradicting it.** That
entry said title match dominates and the Keywords field is the lever. The
correction is that the Keywords field appears to be an **amplifier of terms that
already overlap the title, not a way to reach terms that do not**. `panopto
downloader` reaching #13 while bare `panopto` reaches nothing is the same fact
from the other side: the word carrying that result is *downloader*, which is in
the product name.

**The consequence for strategy is a redirect, not a retry.** `STORE_LISTING.md`
called `panopto`, `notebooklm` and `lecture downloader` *"the cheapest wins on
the board"* because they are uncontested. They are uncontested and they are also
**not reachable through the keywords field**, and the one field that would reach
them is the Product Name, which was deliberately and correctly declined. So the
three slots are better spent on canvas- or course-anchored variants of the same
intent, where the evidence says a keyword actually moves rank.

Suggested replacements, each anchored to a word that demonstrably matches, and
each still inside the 7-term / 40-char / 21-word budget:

```
canvas lecture recordings
canvas course transcripts
canvas study files
```

Re-run the same probe two weeks after any change. The command is in
`STORE_LISTING.md` section 7.7 with the query list in section 2.

## NOT YET: the three directory submissions, and the rating count

Both are open items where the honest reading is *too early*, and recording that
is what stops the next session treating a zero as a defect.

- **AlternativeTo, Product Hunt and Softpedia** were submitted on 27 Aug, about
  five hours before this measurement. All three are moderated. `PLAYBOOK.md`
  section 4 already carries the rule: a submission is not a listing, and only a
  fetch settles it. Nothing to check yet.
- **`RatingCount` is 0**, and it *cannot* be anything else yet. The in-app rate
  card shipped in v2.0.2 and is verified present in the shipped Store package
  (2026-08-25), but `core/store_review.py`'s gate requires **3 distinct days
  with a clean run plus a 7-day floor**. The earliest any user can physically be
  shown the card is therefore around **1 September**, and only if they ran a
  clean download on three separate days first. A zero read before then is the
  gate working, not the feature failing.

  **Do not "fix" this by loosening the gate.** The constraints were chosen so the
  ask never lands on a failed or cancelled run, and the lifetime cap of 3 is the
  protection, not the buttons.

## The standing conclusion is unchanged, and now has a second data point

`0` referring domains, and a crawl budget that is rationing pages Google has
already discovered. The Store is **~94% of installs** (900+ Store against **59
GitHub release-asset downloads across every release ever**, read from the API on
27 Aug: v2.0.2 has 6 Windows and 4 macOS).

That ratio is worth restating because it decides where an hour goes. The website
is a discovery and trust surface, and an AI-assistant surface. It is not the
funnel. The funnel is the Store listing, and the two levers on it are ratings
(gated until September, by design) and keyword terms that overlap the product
name (measured above).
