# Marketing, SEO and launch memory

**Start here.** This folder is the durable memory for everything about the
*website*, *search visibility*, *positioning* and *launch* of Canvas Downloader.
It is the marketing counterpart to `CLAUDE.md` (engineering) and
`tests/audit/` (correctness auditing), and it exists for the same reason those
do: the operator works from several machines, and any memory that lives outside
the repo does not travel and does not survive a reimage.

Anything the repo should own goes in the repo. Write it here, in the same commit
as the change it describes.

---

## The eight files

| File | What it holds | Read it when |
|---|---|---|
| **[FINDINGS.md](FINDINGS.md)** | The register. Every defect and opportunity found, with its evidence, its status, and why anything deferred was deferred. | You are about to "discover" something. Check here first; it is probably already known and possibly already decided. |
| **[STRATEGY.md](STRATEGY.md)** | Positioning, who the user is, the vocabulary rule, and the decisions that are **settled**. | Before writing any copy, choosing a keyword, or proposing a rename. |
| **[SITE_RUNBOOK.md](SITE_RUNBOOK.md)** | How to change the website without breaking it: the page shell, the generator, the release procedure, which tests guard what, how to measure. | Before editing anything under `docs/`. |
| **[PILLAR_VIDEOS.md](PILLAR_VIDEOS.md)** | The six looping demo clips on the homepage: the encoding recipe, why posters are deferred, the poster-frame and PII rules, and how to add, replace or remove one. | Before touching any video or poster under `docs/assets/`. |
| **[BLOG_PLAN.md](BLOG_PLAN.md)** | The blog: what the five existing articles do and do not achieve, the measured demand map, and the phased plan for fixing and extending them. | Before writing, retitling or adding any article under `docs/`. |
| **[PLAYBOOK.md](PLAYBOOK.md)** | The off-site execution plan: threads to answer, directories, communities, ready-to-paste copy, calendar. | When you have an hour to spend on promotion. Open `playbook.html` beside it - same content, rendered, with a status board and copy buttons. |
| **[CHANGELOG.md](CHANGELOG.md)** | What was built and changed, per session, with the measured before-and-after. | To find out what already exists without re-deriving it from the code. |
| **[STORE_LISTING.md](STORE_LISTING.md)** | The Microsoft Store listing: every field's copy, the measured search rankings the keywords are chosen from, the screenshot order, the hero-art and trailer briefs, and the click-by-click submission runbook. | Before touching Partner Center, and before writing any Store copy. Open `store-listing.html` beside it - same content, with copy buttons and live character counts. |

---

## Where things stand, in ten lines

Measured 2026-08-20, with the search lines rewritten 2026-08-23 and the
operator-only lines rewritten 2026-08-24. Re-measure before trusting; these rot.

- **The site IS indexed, and it ranks for the brand query.** Answered
  2026-08-23 from Search Console plus a signed-in browser: `site:` returns
  seven pages with real snippets, the sitemap is submitted and read (11 pages),
  and **Google renders an AI Overview built from our own copy**, citing
  `privacy.html`. This replaces the 2026-08-20 reading below it.
- **The Store is no longer the only surface that ranks**, but it is still the
  only one with traction. The older observation - zero results in three web
  searches, an assistant quoting the Store copy - was taken before the site was
  crawled and no longer holds.
- **The remaining constraint is authority, not crawling.** Indexed and ranking
  for a term nobody searches is an off-site problem, so `PLAYBOOK.md` is now
  the whole lever. Do not spend more time on crawlability.
- On-page technical quality is now **good**: canonical, OG, sitemap, robots,
  structured data on 11 of 14 pages, one `h1` each, no broken links.
- **Three search-facing guide pages** exist (download methods, access after
  graduation, Panopto). A fourth, on NotebookLM, is deferred **because its facts
  could not be verified**, not because nobody got to it. See FINDINGS.md.
- Core Web Vitals are now **good on desktop and mobile**. They were not: mobile
  LCP was 5300 ms (Google's POOR band) until 2026-08-20.
- Off-site presence is **effectively zero**: 1 star, 0 forks, no backlinks
  worth the name. This is the real constraint. First move against it:
  **AlternativeTo, Product Hunt and Softpedia submitted 2026-08-27** - sent, not
  yet confirmed live, and a submission is not a listing until its URL returns
  200. MajorGeeks (email-only, outdated) and Slant (dead) are ruled out. See
  PLAYBOOK.md section 4.
- The brand name is **contested** by a Spotify tool that owns the .com, three
  Chrome extensions and five GitHub repos of the same name.
- The `.edu` help desks own the money query, and **they cannot be outranked**,
  only complemented. Two pages now exist to do that.
- Analytics: **none, by decision**. Search Console and Bing Webmaster only.
- The five things that needed the operator personally are **all done** as of
  2026-08-24. `PLAYBOOK.md` section 1b is now history, not a to-do list. The
  only lever left is off-site: sections 3 to 5 of that file.
- Market is **English-speaking but NOT predominantly US**: by Store installs,
  Philippines 82, US 79, Australia 70, South Africa 62, India 55, Nigeria 27,
  UK 24. This corrects an earlier reading taken from the app's institution
  directory, which measures where tenants are, not where users are.
- The site now carries **social proof**: 800+ installs (Store installs plus
  44 from GitHub) and 100 countries, in the hero strip and in `llms.txt`. The
  Store has **0 ratings and 0 reviews**, so nothing on the site claims an
  opinion, and nothing mentions the absence either.
- The homepage and guide were **75% and 97% `opacity: 0` without JavaScript**,
  `h1` included. **Fixed 2026-08-21** and verified live at 0 hidden words. It
  was a candidate cause of the indexing question above; that question has since
  been answered the other way, so it was insurance rather than the cause.
- **The GitHub social preview 404 is fixed; the custom image is GitHub's to
  repair.** Three uploads of three images each minted a new record and all
  three 404'd, so "remove then upload" does NOT work. Removing the image was
  the fix: the auto-generated card now serves 200. See FINDINGS.md.
- **All five operator-only items are closed** as of 2026-08-24, Bing Webmaster
  and IndexNow being the last. Note Cloudflare Crawler Hints is inert here -
  the site is DNS-only, so the IndexNow key is hosted and posted manually.
- **The Store listing is on v2.0.0 and its Privacy Policy link is a 404.** Both
  are fixed by the v2.0.2 submission, which is prepared in
  [STORE_LISTING.md](STORE_LISTING.md) and not yet submitted. Measured
  2026-08-24: the app ranks **#1 for `canvas downloader`** and is outside the
  top 20 for every other term tried, including the uncontested `panopto` and
  `notebooklm`.

---

## How to continue this work

1. **Read `FINDINGS.md` before investigating anything.** Every entry carries the
   evidence and the date. An entry marked `deferred` has a reason; an entry
   marked `settled` in `STRATEGY.md` is not to be re-litigated without new
   evidence.
2. **Measure before claiming.** This folder's worst mistake so far was a
   confident "performance is fine" derived from a desktop-only measurement,
   when the mobile number was failing. Every performance claim must state the
   profile it was measured on.
3. **Verify in a browser, before and after.** Same rule as `CLAUDE.md`. Two of
   the defects here were geometry that was invisible in code review and obvious
   in one screenshot.
4. **Write what you learn back here, in the same commit.** Mechanism first: what
   broke, how it was measured, and why the obvious fix is wrong.

## What this folder is not

It is not a place for engineering notes about the app itself; those go in
`CLAUDE.md`. It is not a public marketing page; nothing here is served from
`docs/`, so nothing here reaches a visitor.

**It is committed to a public repository.** That is deliberate and consistent
with how this project already works (`CLAUDE.md` documents every bug it has ever
had, in public). If you would rather the competitive analysis and draft forum
replies were not readable by anyone, gitignore this folder, and accept that it
then stops travelling between machines, which is most of its value.
