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

## The five files

| File | What it holds | Read it when |
|---|---|---|
| **[FINDINGS.md](FINDINGS.md)** | The register. Every defect and opportunity found, with its evidence, its status, and why anything deferred was deferred. | You are about to "discover" something. Check here first; it is probably already known and possibly already decided. |
| **[STRATEGY.md](STRATEGY.md)** | Positioning, who the user is, the vocabulary rule, and the decisions that are **settled**. | Before writing any copy, choosing a keyword, or proposing a rename. |
| **[SITE_RUNBOOK.md](SITE_RUNBOOK.md)** | How to change the website without breaking it: the page shell, the generator, the release procedure, which tests guard what, how to measure. | Before editing anything under `docs/`. |
| **[PLAYBOOK.md](PLAYBOOK.md)** | The off-site execution plan: threads to answer, directories, communities, ready-to-paste copy, calendar. | When you have an hour to spend on promotion. |
| **[CHANGELOG.md](CHANGELOG.md)** | What was built and changed, per session, with the measured before-and-after. | To find out what already exists without re-deriving it from the code. |

---

## Where things stand, in ten lines

Measured 2026-08-20, with the last three lines added 2026-08-21. Re-measure
before trusting; these rot.

- The **Microsoft Store listing is the only surface that ranks**. The website
  appeared in **zero** of three web searches, including one containing the
  literal domain. When a search assistant summarised the product it quoted the
  Store copy, not the site.
- **Whether the site is indexed at all is UNKNOWN.** It cannot be determined
  from outside. Google Search Console answers it; the tag is already installed.
  This is the single most important unanswered question in this folder.
- On-page technical quality is now **good**: canonical, OG, sitemap, robots,
  structured data on 11 of 14 pages, one `h1` each, no broken links.
- **Three search-facing guide pages** exist (download methods, access after
  graduation, Panopto). A fourth, on NotebookLM, is deferred **because its facts
  could not be verified**, not because nobody got to it. See FINDINGS.md.
- Core Web Vitals are now **good on desktop and mobile**. They were not: mobile
  LCP was 5300 ms (Google's POOR band) until 2026-08-20.
- Off-site presence is **effectively zero**: 1 star, 0 forks, no directory
  listings, no backlinks worth the name. This is the real constraint.
- The brand name is **contested** by a Spotify tool that owns the .com, three
  Chrome extensions and five GitHub repos of the same name.
- The `.edu` help desks own the money query, and **they cannot be outranked**,
  only complemented. Two pages now exist to do that.
- Analytics: **none, by decision**. Search Console and Bing Webmaster only.
- Five things need the operator personally and cannot be done from the repo.
  They are listed in `PLAYBOOK.md` section 1b.
- Market is **English-speaking but NOT predominantly US**: by Store installs,
  Philippines 82, US 79, Australia 70, South Africa 62, India 55, Nigeria 27,
  UK 24. This corrects an earlier reading taken from the app's institution
  directory, which measures where tenants are, not where users are.
- The site now carries **social proof**: 800+ downloads (767 Store installs plus
  44 from GitHub) and 100 countries, in the hero strip and in `llms.txt`. The
  Store has **0 ratings and 0 reviews**, so nothing on the site claims an
  opinion, and nothing mentions the absence either.
- **75% of the homepage and 97% of the guide are `opacity: 0` without
  JavaScript**, `h1` included, with no `noscript` fallback. Open, with a one-line
  inversion as the fix. This is a candidate cause of the indexing question above.

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
