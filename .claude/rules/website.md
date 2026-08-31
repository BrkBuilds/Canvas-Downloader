---
paths:
  - "docs/**"
  - "marketing/**"
---

# Website and marketing surfaces

> Extracted from CLAUDE.md. Loads only when Claude opens a matching file.
> Each entry states the mechanism, the measurement, and why the obvious fix is wrong.

## There is ONE text ramp and it lives in 25 separate `:root` blocks (2026-08-28)
`docs/` is twenty-five inline stylesheets with no shared file, so every token is
written twenty-five times and drifts independently. Measured before the fix:
**four different `--txt2` values and five different `--txt3` values**, i.e. the
same paragraph rendered at a different brightness depending on which page it was
on. The ramp is now `--txt #e9ebee` / `--txt2 #bfc3c9` / `--txt3 #9599a1`, plus
`--rad-s: 5px`, identical everywhere. It WAS guarded per page by
`tests/test_website_reading_hygiene.py`; that test was deleted 2026-08-31 with
the rest of the editorial website tests (see the note at the end of this file),
so the ramp is now a convention to follow, not a rule that is enforced.
- **The complaint was "bold stands out too much", and the cause was the BODY.**
  Seventeen pages set `--txt2: #94a3b8` = **7.61:1**, with `<strong>` at
  `--txt`'s 15.82:1 - so bold was **2.08x** the contrast of the sentence around
  it. Raising the body to 11.02:1 makes the step **1.48x**; `--txt` barely moved.
  Do not "fix" a shouting bold by dimming the bold.
- **The tint was real and measurable**: the ramp was Tailwind slate, RGB spread
  36/255 on `--txt2`. The replacement holds the same hue at about a third of the
  chroma (spread 3 / 8 / 6), which is what stops it clashing inside the amber and
  green callouts.
- **`guide.html` had `--txt3: #475569` = 2.57:1** driving its entire 30-entry
  sidebar, the worst contrast on the site. The sidebar is a navigation list, so
  it is `--txt2` now, not `--txt3`.
- **A `:root`-only census is not a census.** Retired values were also live in
  `stroke=` on inline SVG icons, in an inline `style` attribute, inside an
  `onmouseout` handler that restored a colour in JS, and in `mac-wizard.css`,
  which is a SECOND copy of the whole scale under `--mw-` names. Grep the WHOLE
  source, not the stylesheets.
- **`canvas-url-directory.html` referenced `var(--muted)`, which was never
  defined**: five declarations were invalid at computed-value time and fell back
  to inheriting full-strength `--txt`, so the table headers and the row count
  rendered at the same brightness as the content they were labelling. An
  undefined custom property fails silently and looks like a design choice.

## A number or a letter is a CHARACTER; the pill is the one shape this UI never draws (2026-08-28)
Step markers were filled circles and section kickers were fully-round pills, in
four colours. Both are the outlier: every other surface here and in the app is a
rounded rectangle, and `mac-setup.html`'s `.badge-15` (4px) and `ol.steps`
(6px) were already drawing it that way. Markers are now mono figures with a
trailing `.`; inline tags are `var(--rad-s)`.

- **A standalone section kicker gets NO box at all** (product owner, same day).
  Squaring the pill was the first pass and it was still wrong: a filled
  rectangle sitting above a heading reads as a status chip stuck ON the section
  rather than a label FOR it, and once the four colours were gone the box was
  carrying nothing. `.label` (guide, engine, privacy, disclaimer) and
  `.sec-label` (index) now match `index.html`'s `.section-kicker`, which was
  already plain text and is the reference: uppercase, `letter-spacing: 0.1em`,
  weight 800, `--txt3`, no background, no border, no padding. Size went 11px ->
  13px, because without a box an 11px kicker reads as a stray caption.
- **The box stays on INLINE badges**, and that distinction is the whole rule: a
  kicker is alone above a heading, while `.pill`, `.cbadge`, `.fbadge`,
  `.ver-pill`, `.status-badge`, `.badge-15` and `.mw-tag-15` sit BESIDE a
  sentence, where the box is what separates the tag from the words. Census
  before changing one: every `.label` on guide and engine is a lone `<div>`
  immediately above an `<h1>`/`<h2>`/`.icon-h2`.
- Six pages now declare `--rad-s` without using it. That is deliberate: the
  ramp block is identical in all 25 `:root`s so a page cannot drift, and the
  next badge added to one of them gets the right value with no thought.
- **Three step lists used three different markers** (a cyan circle in the
  article shell, a grey circle in `mac-wizard.css`, a rounded box on
  `mac-setup.html`). They are one rule now. Census with a border-radius scan of
  `50% | 100px | 999px`; the test allow-lists the things that are round because
  of what they ARE - status dots, a spinner, a toggle knob, a round icon button,
  a blurred glow, and the app's own checkbox/radio affordances reproduced in the
  homepage mocks. Those must stay.
- **`.label.blu` put `--blue #3b71b8` on the page background = 3.94:1**, below
  the AA floor, on "Keep Your Courses Up to Date". Do not lighten `--blue` to fix
  that: it is also the primary button's BACKGROUND, where white-on-it is 4.95:1.
  The kicker went neutral instead.
- **The marker must be an inline-block in the sentence's own line box**, pulled
  into the gutter with a negative margin - not `position: absolute`. `line-height`
  is the unitless value the list inherits, so an absolutely positioned marker at a
  smaller font-size resolves a SHORTER line box (13.2 x 1.75 = 23.1px against the
  row's 26.25px) and sits ~1.6px high. In the line box the browser aligns the
  baselines itself at every font-size the four shells use. Restate `box-sizing`
  on the pseudo-element: the shells' reset is `*`, which does not match one.
- **A flex row of marker + title needs `align-items: baseline`, not `flex-start`**
  (mac-setup's permission list). Measured: the number sat 6px above the title.

## Cyan is this site's LINK colour - spending it on a STATE reads as another link (2026-08-28)
`.nav-link.active`, `.toc a.active`, the "SHORT ANSWER" kicker, section kickers,
bullets and step markers were all cyan. They are neutral or white now; the
sidebar's active row keeps a cyan RAIL, because one accent per element is the
rule that was being broken (cyan text inside a cyan-tinted box inside a
cyan-railed row states it three times).
- **Both gradient-filled headlines are gone** (`index.html` cyan-to-indigo,
  `engine.html` purple-to-cyan). The app draws no gradient text anywhere, so they
  could not have come from the product's design language.

## An un-styled `<a>` is browser blue, and the pages that had one were the pages styling links INLINE (2026-08-28)
`mac-setup.html` had no `a` rule at all, so "step-by-step walkthrough" rendered
in the UA's `#0000EE` at **1.99:1** on a near-black card; `canvas-url-directory.html`
had three more at 2.08:1. Every other link on those pages carried
`style="color: var(--cyan)"` one at a time - which is exactly why the ones that
were missed looked broken rather than merely off-palette.
- **A colour on an ancestor cannot save it.** The UA sheet's own
  `a { color: -webkit-link }` beats INHERITANCE, so `.setup-card { color: X }`
  does nothing for a link inside a setup card. The first version of the guard
  merged those two cases and passed with the fix deleted.
- **The census is a browser one and it is cheap**: `document.querySelectorAll('a')`
  filtered to a computed colour of `rgb(0, 0, 238)`, on every page. It also found
  `blog.html`'s twelve post cards, where nothing rendered blue only because every
  text node inside them happened to set its own colour.

## `outline: none` on a `<summary>` blinds the keyboard, and only the keyboard needs it (2026-08-28)
`guide.html` and `index.html` nulled the outline on their accordion summaries to
stop a ring persisting after a mouse click - a real problem. **Measured by
tabbing the real pages: 11 of 70 stops on guide and 30 of 69 on index had no
focus indicator of any kind**, almost all summaries, and a `<summary>` is the
only way to open one with a keyboard. `:focus-visible` does not match a mouse
click, so adding it restores the keyboard ring and leaves the click behaviour
the `outline: none` was protecting untouched. Verified both directions.
- **`all: unset` in an INLINE style beats the stylesheet**, so the JS-built
  YouTube play button on `guide.html` and `mac-setup.html` stayed ringless even
  after the rule was added. It now lists the properties it actually needs and
  leaves `outline` alone; geometry measured identical (598x336, 0 border, 0
  padding).
- **The other 23 pages were already clean**, which is the census: `outline: none`
  appears in exactly those two files plus one search input that substitutes a
  border colour.

## Collapsing a button's LABEL below 860px is right in the nav and wrong outside it (2026-08-28)
The rule that drops `.btn-nav span` on narrow screens (see the entry below for
why it exists) was unscoped. In the nav each button also carries an SVG, so
dropping the words leaves a glyph; the article CTA box reuses `.btn-nav-ghost`
for a TEXT-ONLY link. **Measured on a 390px viewport: an empty 22x37px box** on
all twelve article pages, where "See it in action" / "Compare all methods" /
"Acceptable use" should be. Now `nav .btn-nav-ghost span`, in all 25 files.
- **Do not census this with the substring `"nav "`** - `.btn-nav span` contains
  it. Check that each selector STARTS with `nav `.
- Three files write the rule differently (860px single-line, 860px multi-line,
  and engine's 900px variant); a single-string replacement reached 21 of 24.

## A heredoc turns `\b` into a literal backspace, and the regex still LOOKS right (2026-08-28)
Two checks in `tests/test_website_reading_hygiene.py` (since deleted) were
written through a shell heredoc and silently compiled to `outline:\s*(none|0)\x08` - a pattern
nothing can match. Both read correctly in `grep`, in `sed`, and in
`inspect.getsource`; the only way to see it was `f.__code__.co_consts`. Both
checks passed on every page while testing nothing, and the mutation pass is what
caught it. `testing-and-audits.md` already records this hazard for anchor-shaped
tests: **any edit whose payload contains backslash escapes goes through the file
tools or a script FILE, never a heredoc.**

## A page's own text must not be `opacity: 0` to a crawler that runs no JS (2026-08-21)
`docs/index.html`, `guide.html` and `engine.html` gate nearly every block behind
`class="reveal"`, which an IntersectionObserver un-hides. Measured with a real
parser: **guide 7,025/7,217 words (97%)**, **index 3,125/4,112 (75%)**, both
with the `h1` hidden. Google renders JS; several assistant crawlers do not, and
`marketing/` records the site appearing in zero of three web searches while an
assistant quoted the *Store* copy.
- **The fix is ADDITIVE and that is the whole point**: one rule on
  `html:not(.js) .reveal`, plus an inline `<head>` script. With JS present
  `html.js` matches so the new rule never applies. **Do not invert it onto
  `html.js .reveal`** - that is (0,2,1) and outranks `.reveal.vis` (0,2,0), so
  nothing would ever be revealed again. Total in a browser, invisible in review.
- **The class means "the mechanism that reveals this exists"**, not "scripting is
  on": it is set only when `IntersectionObserver` is present, because the reveal
  script constructs one with no fallback.
- **Verified against the DEPLOYED pre-fix site, not against a claim**: identical
  reveal count, identical initially-hidden count, identical per-element
  `transitionDelay` ladder, identical computed transition, 0 hidden after
  scrolling. No-JS hidden words 3,125 -> 0 and 7,025 -> 0, confirmed live.
- `tests/test_website_noscript_content.py` derives its page list FROM the markup
  so a new page cannot silently miss the rule; 7/7 control mutants caught,
  including the inversion and a rule that is merely commented out. Two of its own
  assertions were too weak first: a lookbehind that a prefixed selector satisfied
  (compare the WHOLE selector), and reading comment-bearing source instead of
  `<style>` blocks with CSS comments stripped.

## Deep-dive article links do not go in the feature pillars' prose (2026-08-28)
Six links across pillars 1, 4 and 6 of `index.html` were a closing paragraph
inside `.pillar-text`. They now sit in a `.pillar-reading` block at the foot of
each pillar's own expander, which is closed by default: same links, same served
HTML, no vertical space until the reader opens it. **Measured at 1680px**: those
pillar texts were 508/585/629px against 432-457px for the three pillars with no
link paragraph, and `.pillars` was 3,842px; after, 406/483/450px and 3,458px -
**384px removed**, with no pillar text taller than its own video.
- **The SEO argument for inline links is already dead on this site's evidence**:
  link COUNT is anti-correlated with getting crawled here (9 links = never
  crawled, 1 link = indexed - `marketing/SEO_FINDINGS_2026-08-27.md`). The prose
  was paying conversion for nothing. A new deep-dive link goes in the pillar's
  `.pillar-reading` block or the paragraph under the FAQ, never in `.pillar-text`.
- `marketing/` is gitignored as of 2026-08-28, so the long-form version of this
  decision in `STRATEGY.md` does not travel between machines. This file does.

## `thanks-win.html` and `thanks-mac.html` START A DOWNLOAD - never link them from prose (2026-08-28)
Both pages resolve the newest release asset from the GitHub API on load and
**auto-trigger the download**; their whole job is to be the target of a Download
button. The macOS FAQ on `index.html` linked the words "install guide" to
`thanks-mac.html`, so a phone reader tapping a prose link to *read* something
was handed a silent .dmg instead. The guide those words describe is
`mac-setup.html`.
- **The census is the check, not the one link**: `grep -n 'thanks-mac.html\|thanks-win.html' docs/*.html`
  and confirm every hit is a button (`.btn-download`, `.btn-dl`, `#hero-get-*`),
  never body text. Three hits on index at the time of the fix; the two button
  ones are correct and must stay.

## The nav's Download button collapses to its icon at 860px, like every other page (2026-08-28)
`index.html` used to keep the word "Download" on phones, on the argument that an
unlabelled glyph is a weak CTA. **Measured on a 360px viewport**: the labelled
button made `.nav-right` 157px wide, starting at x=208 - exactly where the
"Canvas Downloader" wordmark ends, gap **0px** - and running to x=365, five
pixels past the viewport, so `document.body.scrollWidth` was 365 against a 360px
`clientWidth`: the whole page scrolled sideways. After: button 33px, gap 26px,
scrollWidth == clientWidth. The wordmark is `white-space: nowrap`, so it cannot
absorb the squeeze; `.nav-logo` now also carries `min-width: 0; overflow: hidden`
so a future squeeze clips characters instead of landing on the title.
- The CTA loses nothing on a phone: the href is a desktop .exe/.dmg the visitor
  cannot install there.

## A `+`/`-` expander toggle needs its gutter in its OWN box (2026-08-28)
Long summary titles ran flush into the toggle glyph (`What does it actually
connect to?+`). The glyph is a `::after` pushed right by `margin-left: auto`, so
a `gap` on the summary is the wrong tool - it also spaces the leading icon, and
`.mac-note` already sets its own. **`padding-left` on the pseudo-element is
empty space inside a box whose right edge is already pinned**, so the glyph does
not move on a wide screen and the title wraps instead of touching it.
- **Two families, both had it**: the flex form (`margin-left: auto`) in
  `index.html` and `guide.html`, and the `float: right` form in all 12 article
  pages, which needed `margin-left` instead. Census with
  `grep -rn "summary::after" docs/*.html`; the `[open]` rules only swap
  `content` and inherit the gutter, so they are not separate sites.

## Outreach copy is a SUMMARY of the articles, so check it against them before it is sent (2026-08-28)
Three emails to university help desks and one public Instructure comment went out claiming
**"Pages and assignment briefs have no bulk export at any permission level a student holds."**
It is wrong, and `docs/` already said so. `save-canvas-pages-quizzes-discussions.html` documents
`Export Course Content` on the Modules page under "The one built-in route, and its expiry date" -
browsable offline HTML, **Pages included** - and `back-up-canvas-course-before-losing-access.html`
documents the ePub route under Account. Both are real student-side bulk exports.
- **The claim looked true because both routes are feature-flagged off by default**, per
  institution or per course, so most students never see either. The accurate line is about the
  flags, not about Canvas, and it is a better line: *"if those flags are off, your students have
  no bulk route at all; if they are on, Instructure's own limit is that 'Offline content cannot be
  downloaded once a course is concluded', which is exactly when a graduating student looks."*
- **The recipients administer those flags.** A factual error in outreach is worst in front of the
  one audience qualified to spot it, which is the audience this channel targets by definition.
- **A forum answer is not a primary source.** The bad fact entered `marketing/FINDINGS.md` from the
  accepted answer on Instructure Community discussion 618390 (*"I'm not sure of a quick way off the
  top of my head"*) and was never rechecked, while the site's own research contradicted it.
- **The check is one grep**, and it is now rule 7 in `edu-outreach.html`: before sending, grep
  `docs/` for the claim you are about to make. The articles are the research; the email is a
  summary of it, and a summary that contradicts its source is the error, not the source.

## The AI tell in outreach prose is that NO SENTENCE IS SHORT (2026-08-29)
Seven emails to university help desks were written from one skeleton and read, in the product
owner's words, as obviously machine-written. Scored with `scripts/check_ai_writing_tells.py`, the
same scanner that fixed the blog articles, the signature is countable and it is not vocabulary:
**six of the seven contained zero sentences of eight words or fewer**, against 18 to 33% in the
rewrites, with contractions at 6.8 to 14.4 per 1k against 35 to 51.
- **A person writing to a help desk drops in "Thanks." or "That one looks like a quick fix."**
  The template never did. Uniform sentence weight across a whole email is the thing a reader feels
  and cannot name, and both halves of it are countable before sending.
- **Do not overcorrect.** The first Boston College rewrite came back at sd 6.2 with no long
  sentence at all, which is the same tell in different clothes. `BLOG_PLAN.md` section 10 sets the
  benchmark at a standard deviation near 9 to 10; the three accepted rewrites landed 8.8 to 9.3.
- **The structural half matters more than the numbers.** Seven emails shared an opening move, a
  "two things it does not cover" middle and several verbatim phrases. Vary what each email is FOR:
  one reports a defect on their page, one agrees with them first, one carries a single gap and
  stops. A message shaped like the last one is a template however well it scores.
- **The scanner takes docs slugs, not free text.** The wrapper that scores plain email bodies is
  twenty lines and reuses `sentences()`, `BANNED_WORDS` and `NEG_PARALLEL` from the module rather
  than restating them. Never restate the rules: a second copy of the lexicon is the same defect
  this repo has recorded three times elsewhere.
- **Two content rules for institutional mail**, from the same session: the full URL goes in
  brackets immediately after the article title, with its KB or Article ID, because these are
  ticket systems holding thousands of articles and a title alone forces a second email. And never
  write `GPL-3.0` to a learning-technology coordinator; say that the code is public and that it
  runs on the student's own computer.
- **The inbox preview is the first line, and the template wasted it.** A mail client shows the
  subject then the opening words of the body. The seven sent emails opened with a standalone
  "Hello," and a compliment, so the preview read as flattery while the finding sat in paragraph
  two, and several restated their own subject in the first sentence. Three rules: no standalone
  greeting (there is no name to put in it), the first sentence carries the finding, and it must
  ADD to the subject rather than repeat it.

## Structural furniture holds `--txt`; only META stays `--txt3` (2026-08-29)
"SHORT ANSWER" and "ON THIS PAGE", their body copy and the TOC's numbers were `--txt3` /
`--txt2` on all twelve article pages, and the product owner read them as secondary: these are
the two devices that tell a skimmer what the page answers and where to go in it. All four are
`--txt` now. The line is what the element DOES, not where it sits: a card label that guides
the read is structural, a credit line is meta.
- **The numbers needed the colour stated on `.toc li`, and nowhere else.** `.toc li` set only
  `margin-bottom` and `font-size`, so `.art li { color: var(--txt2) }` painted every TOC row,
  and `::marker` takes its colour from its OWN originating `li`. Setting it on `.toc` or
  `.toc ol` does not reach the marker; setting it on `.toc p` colours the label alone. The
  links inside stay cyan, because a TOC entry is a link and cyan is this site's link colour.
- **Do not reach for `--txt3` itself.** It is the shared meta token: the byline, the footer,
  every section kicker, the FAQ `+`, and `.author-box p.ab-label` all read it. Verified in a
  browser after the change that byline, ab-label and footer are still `rgb(149, 153, 161)` and
  `.art` list items still `rgb(191, 195, 201)`, while all four targets are `rgb(233, 235, 238)`.
  A token edit here would have whitened the whole site's meta layer in one move.
- **"Who wrote this" stays `--txt3` on purpose.** The author box sits under the FAQ and states
  provenance; nobody navigates by it. Same for the sticky sidebar "On this page" on
  `guide.html` and `engine.html`, where `--txt` is what marks the ACTIVE row: whitening that
  title would spend the state colour on furniture.
- **The tradeoff is real and was accepted**: `.art strong` is already `--txt`, so bold inside
  the short answer now differs by WEIGHT only. That is the same treatment `.lede` gets, which
  is the block this one is a sibling of.
- The four rules are byte-identical in all twelve pages, so one exact-string replacement
  reaches every page. Assert the count is 12 before writing, per the entry above about a
  single-string replacement that reached 21 of 24.

## `docs/sitemap.xml` has no generator, so its `lastmod` lies after every push (2026-08-29)
Commit `ef2eb1ae` changed **19** pages under `docs/` and did not touch the sitemap, so all 22
`lastmod` values still read `2026-08-27` while the deployed pages were a day newer. `lastmod` is
how a search engine decides whether a URL is worth re-fetching, and crawl budget is this site's
measured binding constraint, so a stale date throws away the one legitimate way to ask for a
re-crawl.
- **Only Google was misled.** `scripts/ping_indexnow.py` derives its changed set from `git diff`,
  not from the sitemap, so Bing got the correct list on the same push. Two engines were being told
  different things and only one of them the truth.
- **Fix:** `python scripts/sync_sitemap_lastmod.py --write`, committed in the SAME commit as the
  page change. The script is still here and still correct; `tests/test_sitemap_lastmod.py` was
  deleted 2026-08-31, so running it is now a habit rather than something CI insists on.
  `test_website_internal_links.py` survives and still fails when a `<loc>` has no file behind it,
  which is the 404-announced-to-two-engines half of what that test covered.
- Mutation-checked three ways: a reverted date, a deleted `<lastmod>` tag, and a `<loc>` pointed
  at a file that does not exist. All three fail as they should.

## Bing Keyword Research sees BRAND queries only, at any phrase length (2026-08-29)
The 2026-08-28 run read its own floor as a phrase-LENGTH limit: `panopto` (28.5K) and `canvas
download` (7.3K) answered while every phrase of three words or more did not. Twenty short probes
on 2026-08-29 falsify that. **The split is whether the phrase carries a product NAME.**
Answered: `notebooklm` 3.2M, `kaltura` 12.3K, `echo360` 3.5K, `moodle download` 3.1K, `canvas
studio` 2.2K, `panopto download` 638, `canvas videos` 317. Silent, at two words as readily as at
five: `canvas files`, `canvas backup`, `canvas export`, `canvas quizzes`, `canvas token`, `canvas
transcript`, `panopto transcript`, `course download`, `course backup`, `lecture download`,
`lecture recordings`, `study files`. Across both runs that is **34 generic phrases with no data**,
so the instrument measures brand and navigational demand and cannot see task demand here at all.
**Do not run generic probes again**; the answer is known and it is not "no demand".
- **FIVE intent traps, and they are the run's most useful output.** An impression count is not
  demand for what you sell, and the `Top 10 url ranking` panel says so in one look. `panopto
  download` (638) is **10 of 10 "Install Panopto for Windows"** - the recorder, not a lecture.
  `moodle download` (3.1K) is the Moodle app. `canvas transcript` is an **academic** transcript
  (Parchment, "transcript of my enrollments"). `course download` is Udemy and r/Piracy. `canvas
  videos` (317) returns a related list that is **100% Canva**. Read the SERP panel before
  believing the number: five of eight numbers this run produced belong to someone else's intent.
- **The UK Panopto gap is confirmed on a second phrase.** `panopto download` is 153/638 =
  **24% UK** against 21% on bare `panopto`, and the `panopto transcript` SERP carries
  `digi-ed.uk` and `imperial.ac.uk`. The UK is 2.9% of installs.
- **`notebooklm` is 3.2M and its biggest market is INDIA**, 401.2K against the US's 140.1K and the
  UK's 22.4K. India is a top-five install market. Its 3M trend is **falling** (about 310K to
  230K), so it is large and cooling, not large and growing.
- **The platform gap is a measured NON-opportunity and must stay recorded as one.** `kaltura`
  12.3K + `echo360` 3.5K + `canvas studio` 2.2K = **18K against panopto's 28.5K**, so the lecture
  platforms this app does not reach are two thirds the size of the one it does. That reads as a
  roadmap item and is not one: **the product owner's university runs none of them** (stated
  2026-08-29), so nothing there can be built, tested or verified first-hand, which is this site's
  whole evidence standard. `download-lecture-videos-from-canvas.html` already documents Kaltura
  and Studio from Instructure KB 664517 / 660507 and Michigan MiVideo KB 10274 and says the app
  handles Panopto only. That is the finished answer. The one real gap is that **`echo360` appears
  nowhere in `docs/` or in the generator**, and it belongs as a row in that article's five-system
  table, sourced the same way, and nothing more.
- **The SERP panel found five competitors the register does not list**: `Ryfter/canvas-backup`
  (positions **1 and 5** on `canvas backup`), `classbackup.com`, `canvasexport.com`,
  `techconsigliere/CanvExporter`, and a `Panopto Captions and Video Downloader` Chrome extension
  ranking on `panopto transcript` where we do not. `STRATEGY.md` section 5 was rebuilt from the
  tools' own docs on 2026-08-27 and is **stale again three days later**; rebuild it from the
  repositories, never from search snippets.

## Every article on this site ends by selling the app, so no page is citable by the people who publish links (2026-08-29)
Census of `.cta-box` across `docs/`: **12 of 12 generated articles carry one**; the only
search-facing pages without are `canvas-url-directory.html` and `blog.html`. Every article is
therefore addressed to a student mid-task, and students do not publish links. The audiences that
do - help desk and learning-technology staff, accessibility officers, tool builders, subreddit
wiki editors - have no page here, and a page that closes with a Download button has to be edited
before a university KB can cite it.
- **This is a different defect from "nothing linkable has been built".** Two linkable assets
  shipped 2026-08-27 (`what-canvas-download-as-zip-misses.html` and the URL directory) and one of
  the two still ends in a CTA. The asset thesis was right; the reader it was aimed at was not.
- **The outreach inherits it.** `edu-outreach.html`'s emails cite
  `save-canvas-pages-quizzes-discussions.html` and
  `back-up-canvas-course-before-losing-access.html`, both of which carry a CTA box, so a cold mail
  from a stranger links to a page selling software. That is a better explanation for the reply
  rate than the sentence rhythm the entry above this one fixed.
- **Do not fix it by removing CTAs from the twelve.** They are the conversion element and
  `BLOG_PLAN.md` phase 0b settled that argument with the reasoning. The fix is one page that never
  had one.

## `docs/` publishes no machine-readable data, so the one dataset this project owns cannot be cited (2026-08-29)
There is no CSV and no JSON anywhere under `docs/` (checked 2026-08-29; the only non-HTML files
are the IndexNow key, `CNAME`, `robots.txt`, `sitemap.xml`, `llms.txt`, two CSS files and one JS).
`shared/institutions.py` holds **4,757 Canvas hostnames, each proven live against
`/api/v1/users/self` at generation time**, and it reaches the web only as a 957 KB HTML table.
- **A builder who consumes a CSV cites it; a builder who scrapes a table copies it.** A dataset at
  a stable URL, with a licence and a stated method, is the shape that attracts a citation, and
  publishing one costs no article and no new prose.
- **Size the win honestly.** GitHub renders README links `nofollow` (measured 2026-08-28), so a
  repository citing the data passes no ranking signal. What it passes is discovery and credibility
  with builders, plus a chance of a dofollow wherever a dataset gets written up.
- **State the coverage rather than hiding it**: 1,558 of 4,757 rows carry a country, across 40
  countries, US 1,330. The directory page already makes the "not exhaustive" point and the data
  files must repeat it.

## THREE generators were behind their own output, so any build reverted shipped fixes (2026-08-29)
Every hand-applied CSS fix from 2026-08-28 and 2026-08-29 was written into the
GENERATED file under `docs/` and never back-ported to the script that writes it.
Running the build script therefore silently reverted them. Found by running the
builds, not by reading anything.

| Generator | What a rebuild destroyed |
|---|---|
| `build_institution_directory.py` | the base `a { color: var(--cyan) }` rule (**4,760 anchors** fall back to the UA's `#0000EE` at 2.08:1 without it), `#dirq:focus-visible`, and five `var(--muted)` declarations of a variable this site never defines |
| `build_guide_pages.py` `ARTICLE_CSS` | the step marker as an inline-block CHARACTER (reverted to the round cyan circle the pill entry retired), `margin-left: 12px` on the FAQ `summary::after`, `.short-answer` label and body at `--txt`, `.toc p` and `.toc li` at `--txt` - **four documented fixes, on all twelve article pages at once** |
| `build_guide_pages.py` `build_index` | `.post { color: var(--txt) }` on `blog.html`, whose cards are each one big `<a>` |

- **The `ARTICLE_CSS` reversion was caught by *reading the diff* of a page nobody
  had touched**, which is the cheap habit: after running any build script,
  `git diff` a file you did not intend to change.

### RESOLVED 2026-08-31 by DELETING the article generator. Do not reintroduce it.
`scripts/build_guide_pages.py` (719 lines) and `scripts/guide_pages_content.py`
(4,784 lines) are gone. The entry above is why: a script that rebuilds prose from
a Python file has no way to know which of the two copies is newer, so every run
is a coin flip on somebody's hand-edit, and it had already lost that flip twice.

**An article is a document, not a build artifact.** The thirteen articles,
`blog.html`, and every other page under `docs/` are now hand-maintained, edited
in place like any other file. Nothing regenerates them. Stated by the product
owner 2026-08-31: *"an article is an article, and does not need to be regenerated
at any point in time. Edited, yes, rebuilt from the ground up multiple times,
NO."*

- **TWO generators remain and they are a different thing**:
  `build_institution_directory.py` and `build_data_exports.py`. Those bodies are
  4,757 rows derived from `shared/institutions.py` - a table, not writing - so
  they must be built. They now take the shell from `scripts/site_shell.py`, which
  is the only thing salvaged from the deleted script.
- **`site_shell.py` still lifts the nav, footer and stylesheet from
  `docs/win-setup.html`**, so a nav change there reaches the two data pages on
  the next build. Every other page needs the edit applied to it directly.
- **The ARTICLE_CSS that the deleted generator injected now lives only in the
  thirteen pages themselves**, which is correct: it is their stylesheet and they
  are the source of truth for it. A CSS change across the articles is now a
  13-file edit and there is no second copy to drift from.
- The old rule "before editing anything under `docs/`, check whether a script
  writes it" now has a two-file answer: `canvas-url-directory.html` and
  `canvas-data.html`. Everything else is hand-maintained.

## The checklist page is a different SHAPE, and that is the whole experiment (2026-08-29)
`canvas-end-of-semester-checklist.html`, the thirteenth article and the first that
is not a long-form how-to. Twelve articles, ~20,700 words of prose, all the same
object: TOC, prose, FAQ, CTA. A reader who bounces off one bounces off all of them.
- **Its distinct claim is the five switches**, not the download list. Article 6
  already owns "what to save and in what order". What nothing on the site or
  anywhere else says is that **five institution settings decide what a student is
  ALLOWED to save, none is announced, and none can be checked after access ends**:
  student token creation, `Export Course Content` on the Modules page, `Files` in
  course navigation, the Panopto download permission, and captions. Written as a
  duplicate of article 6 it would have been a near-duplicate in Google's eyes too,
  which matters when the measured constraint is indexing rather than crawling.
- **`page_css` is a new `build()` parameter**, defaulting to empty, appended after
  `ARTICLE_CSS` inside the same `<style>`. The other twelve pages carry not one
  extra byte. A page-specific device belongs there, not bolted onto the shared
  sheet.
- **The print stylesheet is the feature, not decoration.** A checklist that cannot
  be printed is an article about a checklist. Print drops nav, footer, CTA,
  byline, author box, TOC and the whole FAQ, repaints black-on-white, and
  **writes every source URL out after its link** with `a.src::after { content: " (" attr(href) ")" }`,
  because a reader on paper cannot hover. Verified by enumerating every selector
  in the `@media print` block against the live DOM: **17 selectors, 0 dead**. That
  is the check worth copying - a print rule aimed at a class the page never
  renders is invisible until somebody prints.
- **The checkboxes are native**, styled only with `accent-color`, so they keep
  their own focus ring and keyboard behaviour. Every one of the 18 has a `<label for>`
  and clicking the text toggles the box (verified by driving a real click). There
  is no JavaScript and no persistence: it is worked through in one sitting or
  printed, and adding storage would be the first script on a page that needs none.
- **Measured on the writing targets**: sd **9.6** against the 9-10 benchmark,
  **0.0** dashes per 1k, 4% long sentences, 0 negation constructions. short% is
  16%, slightly under the 18% floor, and was left alone deliberately - the target
  is VARIANCE, and padding prose to move a number is the behaviour the scanner
  exists to catch.

## A question-shaped HEADING is not a rhetorical question (2026-08-29)
`check_ai_writing_tells.py` flagged two "rhetorical questions" on the checklist
page. Both were its own `<h3>` section headings - *"2. Is there an Export Course
Content button?"*, *"3. Is Files in the course navigation?"* - which are questions
by design and are how the page matches the phrasing a reader types.
`RHETORICAL_Q` is defined as a MID-PARAGRAPH self-question, and stripping tags runs
a heading straight into the next paragraph's opening capital, which is that pattern
exactly. **Third time a checker on this site needed fixing before its number meant
anything**, and the same family as the FAQ headings and the table cell already
recorded in `BLOG_PLAN.md` section 10.
- `visible_text()` now strips `<h1>`-`<h6>`, exactly as it already stripped the
  TOC, tables and the FAQ: remove what the metric never claimed to be reading.
- **It cannot hide a real hit**, because a genuine mid-paragraph self-question
  lives inside a `<p>`, which is untouched. Controlled both ways: a comma-splice
  question and a run-on question are still caught; a question-shaped heading is
  not; and **2 of the 13 pages still score 1**, so the guard can still say yes.
  A metric that goes to zero everywhere has been broken, not fixed.
- **The first control was wrong and that is the lesson.** "The files were there.
  So why did nobody notice?" is NOT matched - the regex needs `[a-z,]` before the
  capital, so a question after a full stop never matched and never did. Check what
  your control actually exercises before reading its result as a pass.

## The constraint is INDEXING, not crawling, and that retires the no-new-pages rule (2026-08-29)
Read from Search Console by the product owner: the six pages published 2026-08-27
are **crawled and not indexed**, and indexing was requested for each. The
2026-08-27 reading in `marketing/SEO_FINDINGS_2026-08-27.md` concluded from five
earlier pages that *publishing divides the crawl budget*, and that conclusion has
been the standing reason not to write anything new.

**It is falsified in its crawl half.** Six more pages went into the same budget
and Google fetched them. Discovery works, scheduling works, and adding a page does
not starve the others.

- **"Crawled - currently not indexed" is a SELECTION verdict, not a budget one.**
  Google fetched the page and declined to store it. The levers are therefore
  distinctness and authority, not internal links, not sitemap priority, and not
  restraint about publishing. Requesting indexing is worth doing once per URL and
  is not a fix.
- **The practical consequence for writing:** a new page that restates an already
  indexed page competes with it for the same slot and loses. That is why
  `canvas-end-of-semester-checklist.html` is built around the five institution
  switches rather than around what to save, which
  `back-up-canvas-course-before-losing-access.html` already covers. Ask what a new
  page says that no indexed page says, and if the answer is "the same thing more
  conveniently", it is a section, not a URL.
- **Do not re-derive the crawl-budget rule from the old entry.** It was correct
  about what it measured at n=5 on an eight-day-old property and it is superseded.
- **Bing AI Performance was opened and it is empty**: 0 total citations, 0 cited
  pages, 0 grounding queries, over 3M. The site is not yet indexed on Bing long
  enough to be grounded on, so this is *no data yet*, with the reason known. It is
  the right instrument for `docs/llms.txt` and it stays on the list to re-read, not
  as an open question about whether the GEO work landed.

## Getting "crawled - currently not indexed" pages indexed: what is actually true (2026-08-29)
Researched against Google's own documentation and the July 2026 Search Off the
Record episode, then two site-side hypotheses were tested locally. **Both came
back negative, which is what makes the conclusion usable.**

**Google's own words, and they close two doors:**
- `ask-google-to-recrawl`: *"There's a quota for submitting individual URLs and
  requesting a recrawl multiple times for the same URL won't get it crawled any
  faster."* So re-requesting indexing does nothing. Request once, then stop.
- Same page: *"Crawling can take anywhere from a few days to a few weeks."*
- The **Indexing API is not an option**: *"The Indexing API can only be used to
  crawl pages with either `JobPosting` or `BroadcastEvent` embedded in a
  `VideoObject`."* Every blog and tool recommending it for ordinary pages is
  recommending a policy violation.

**Mueller and Splitt, "How to read the Indexing Report", 16 July 2026. It is a
SITE-level judgement, not a page-level one:** *"if our systems are seriously
worried about the quality of the website that they will reduce the number of
pages at the index"*, and *"if we have strong concerns about the overall quality,
then it doesn't make much sense for our systems to spend a lot of time on the
website"*. The advice is *"you almost need to take a step back and think about the
quality overall"*. The failing bar, in his words: *"There's nothing unique or
valuable that is available here for me... Anyone could have written this. This
tells me nothing."* He also states a healthy site does **not** need a 100% index
rate. Google reps at Search Central Toronto, April 2026, put the passing bar as
**personal experience and knowledge no one else possesses**.

**MEASURED HERE, and both hypotheses are dead:**
- **Self-cannibalisation: ruled out.** Pairwise 5-word-shingle overlap across all
  thirteen articles peaks at **2.2% Jaccard / 4.5% containment**
  (`back-up-canvas-course` against the checklist). Duplicate detection operates an
  order of magnitude above that. No article is competing with another one here.
- **Thin content: ruled out.** 1,142 to 2,605 words of extracted prose per page.
- **Every waiting page except two is linked from a page Google has already chosen
  to KEEP** (`blog.html`, `canvas-access-after-graduation`,
  `save-canvas-assignment-feedback`). The exceptions are `canvas-data.html` and
  `canvas-url-directory.html`, which are deliberately not in `blog.html` because
  they are tools rather than articles. That is the one concrete, cheap thing left
  on the site side, and it is a DIFFERENT mechanism from "add more internal
  links", which this site's own crawl data already killed.

**So the answer is the one the register already had, arrived at from the other
end: it is site-level authority, and nothing on the page moves it.** Note also
that the six pages were **two days old** when this was read, against Google's own
"a few days to a few weeks". Calling that a defect now would repeat this folder's
worst historical error, which was a confident verdict from the wrong measurement.

**What follows for what gets written.** Google's stated bar is content nobody else
could have produced. Two pages here clear it unambiguously and both are first-hand
measurement: the 33-course census and the Whisper CPU timings. **The prediction to
judge this on: those index before the explainers do.** If after four to six weeks
nothing has indexed, the thing to reconsider is not the writing but whether
thirteen articles is more than a three-week-old domain's authority supports -
Mueller is explicit that every indexed page counts toward the site's quality
judgement. Do not act on that before the wait.

**Do not:** re-request indexing (stated useless), touch the Indexing API (policy),
buy an indexing service (the entire search result set for that query is link
spam), add internal links (anti-correlated here), or publish more explainers to
"build topical authority" (that adds pages to a site that may already have more
than it can carry).

## `.post p` silently overrode `.post-meta`, so the blog index's date line was never its own size (2026-08-29)
The product owner read `blog.html` and said the "9 MIN READ" line looked bigger
than the sentence introducing the article. It did, and it was not a taste
judgement: **`.post-meta` declared `font-size: 12px; color: var(--txt3)` and
computed to `15px` and `var(--txt2)`**, because `.post p` is **(0,1,1)** and
`.post-meta` is **(0,1,0)**, and the more specific rule sat later in the file. The
date line had never once rendered at its intended size or colour.
- **At the same px as the body text but bold, uppercase and letter-spaced, a line
  reads LARGER.** That is why it was visible to the eye and invisible in the
  source: both numbers say 12px there.
- **The fix is DISJOINT selectors, not a more specific one.** `.post p:not(.post-meta)`
  cannot be re-broken by someone reordering the stylesheet; `.post p.post-meta`
  would win today and lose again the next time a rule is added below it.
- **Read the computed value, never the declaration.** The whole diagnosis was one
  `getComputedStyle` call against the declared value, and it is the same technique
  that found the 2.31:1 CTA button and the `var(--muted)` that was never defined.
  Enumerating which rules MATCH an element (`el.matches(r.selectorText)` over
  `document.styleSheets`) is what names the culprit rather than just the symptom.
- Scale after, measured: meta **11px/600/--txt3**, dek 13.5px, title 18px (was
  23px). The hierarchy is now monotonic, which it was not.

## blog.html is two columns, and the footers had to be pushed (2026-08-29)
`.post-list` is a grid, one column below 860px and two above, with
`.container.wide` widened to **1080px on this page only** - at the articles' 800px
reading measure two columns give ~380px each, which is too narrow for a
three-line title. Page height went **3,271px to 1,918px** at 1680px wide.
- **A grid already makes cards the same HEIGHT; it does not align their
  CONTENTS.** With cards of unequal dek length the "Read the guide" line sat at a
  different offset in each, which is the thing that actually reads as ragged. The
  card is a flex column and `.post-more` takes `margin-top: auto`. Measured after:
  **0px footer spread on all six rows.**
- **The left-aligned intro paragraph was deleted, not re-centred.** It said the
  articles were written for students, checked against documentation and honest -
  which every page claims, so it told a reader nothing, and it was the only
  left-aligned block on a centred page. Removing furniture beats aligning it.
- **`.blog-tools` closes a real gap**, not just a layout one: `canvas-url-directory.html`
  and `canvas-data.html` were the only two pages with NO path from any page Google
  has chosen to index. One centred line at the foot of the index gives them one.

## Tests are for the APPLICATION. The website gets health checks and nothing else (2026-08-31)
Stated by the product owner: *"Tests are meant in 99% of cases FOR THE
APPLICATION, NOT for the website, other than critical website health stuff if we
really need it."* The example he gave is the shape to avoid: a guard that fires
because he edited an install count by hand, on his own site, is asserting that
the writer is wrong and the test is right, which is backwards for prose.

**Deleted 2026-08-31** (761 lines): `test_website_login_claims.py` (policed what
pages may say about the login screen), `test_website_reading_hygiene.py` (policed
design tokens and link colours across 25 pages), `test_sitemap_lastmod.py` (tied
CI to a sitemap-freshness workflow).

**Kept, and the line between them is "is the site broken" versus "is the site
written the way some session decided"**:

| Kept | Why it is health |
|---|---|
| `test_website_internal_links.py` | a link that resolves to nothing is a 404 for a real visitor, and a `<loc>` with no file behind it is a 404 announced to two search engines |
| `test_website_download_links.py` | the two installers must be reachable from static markup - this is the conversion path, and it broke once already when the version only appeared via JS |
| `test_website_noscript_content.py` | the `html:not(.js) .reveal` rule; without it 75-97% of a page's words are `opacity: 0` to a crawler that runs no JS |
| `test_website_advertises_shipped_version.py` | a download URL pointing at a release that does not exist is a dead button |

**Do not add a website test that asserts wording, a number a human types, or a
colour.** If a page says something wrong, fix the page.

## PageSpeed Insights, 2026-08-30: the LCP element was being ANIMATED IN
Lighthouse 13.4.1 on `canvasdownloader.app/`. Mobile **95 / 92 / 100 / 100** and
Agentic Browsing **2/3**; desktop **100 / 96 / 100 / 100** and Agentic **100**.
Everything below was fixed 2026-08-31 and verified in a real browser at both
viewports.

- **The single biggest number was not in any of PSI's "opportunities".** LCP
  subparts, mobile: TTFB 10ms, resource load delay 280ms, resource load duration
  250ms, **element render delay 2,710ms**; desktop 5 / 153 / 148 / **1,018ms**.
  The hero image had its bytes after ~540ms and could not become the LCP for
  another 2.7 seconds, because it sat inside `<div class="hero-visual reveal">`
  and **`.reveal` starts at `opacity: 0`** - an element at opacity 0 is not a
  paint. So LCP waited on script parse, the IntersectionObserver, the sibling
  `transitionDelay` ladder and a 0.55s fade. **Above-the-fold content must never
  carry `.reveal`**: it is never waiting to be scrolled into view, only waiting
  on its own animation. Speed Index 4.2s against a 1.1s FCP was the same
  mechanism showing up twice.
- **`link-name` scored 0 on mobile and 1 on desktop, and the difference IS the
  diagnosis.** Below the nav breakpoint `nav .btn-nav span` is `display: none`,
  so both nav buttons became icon-only links with no accessible name. Desktop
  never hits that CSS, so a desktop-only run says the site is fine. **The same
  failure was the only thing costing the Agentic Browsing point** - one
  `aria-label` on each fixed both categories.
- **A form factor is not a page.** PSI tested `index.html` only, and the census
  found the class everywhere: **25 pages** with unlabelled nav buttons, **22**
  with no `<main>`, **26** with a redundant logo `alt`. Always census the class
  across `docs/` before calling a PSI finding fixed.
- **`heading-order` and `landmark-one-main` failed on BOTH form factors** and
  were the only Accessibility deductions desktop still carried, i.e. the two
  cheapest fixes were the highest-value ones. The homepage jumped `h1 -> h4`
  ("Hi, I'm Birk."), `win-setup.html` had no `<h2>` at all, `canvas-data.html`
  jumped `h1 -> h3`. All three rules were SCOPED selectors (`.setup-card h3`,
  `.dl-card h3`), so the tag swap moves the selector with it and is
  presentation-identical.
- **`engine.html` and `guide.html` had 8 more jumps; fixed the same day, and the
  METHOD is the transferable part.** Their levels carry styling through scoped
  selectors, so a tag swap silently unstyles the heading unless the selector moves
  with it. The safe procedure, run in a browser before touching anything: for every
  heading, record `getComputedStyle` AND enumerate which stylesheet rules match it
  (`el.matches(rule.selectorText)` over `document.styleSheets`). That census is what
  proves a tag is safe to move - engine's 16 bare `h5` were ALL `.kv-c` matched by
  one rule, its 4 bare `h4` all `.step-b`, and no bare `h3` rule existed to collide
  with. Then re-measure after and require every value byte-identical.
- **The tag is not the unit; the CONTAINER is.** guide has 15 `<h5>`: 8 in
  `.step-card` correctly under an `h4`, and 7 in `.cat-card` under an `h3`. Only the
  seven move, so the edit is scoped to that section of the file rather than applied
  to the tag. A blanket `<h5>` -> `<h4>` would have broken the eight that were right.
- **One `.info-card h4` sat under an `h2` while the other 19 correctly followed an
  `h3`.** The rule became `.info-card h3, .info-card h4` rather than a second copy -
  verified first that 0 `h3` existed inside any `.info-card`, so widening it cannot
  restyle anything else.
- **`python -m http.server` plus a browser CACHES the page**, and a stale render
  reads exactly like a failed edit: the first post-change measurement found no `h3`
  at all and the file was correct. Add a `?v=N` cache buster before believing a
  negative.
- **The redundant `alt` is a judgement, not a sweep.** `alt="Canvas Downloader"`
  on the logo repeats the link text beside it on 26 pages, so it is decorative
  and becomes `alt=""`. On `404.html` the same file is a standalone logo with no
  text naming it, so its alt is CORRECT and was left. A blind replace would have
  broken the one page that needed it.
- **Cache TTL 10 minutes on all 257 KiB is GitHub Pages and cannot be fixed from
  this repo.** Only a CDN in front changes it. Stop re-finding this.
- Image delivery, 176 KiB: `icon.png` was **1024x1024 for a 28/24/64 CSS px**
  render (41.9 KiB -> 2.8 KiB as `assets/icon-128.webp`), and the hero was one
  1200w file for a 637 device px mobile render (178.5 -> 68.3 KiB via a
  600/900/1200 `srcset`). The 1200w stays: the visual track is ~726 CSS px on a
  wide screen, which needs 1452 device px at 2x DPR.

## Round 2, measured on the LIVE fixed site (2026-08-30 23:29-23:32)
Confirms the round-1 diagnosis and surfaces three things one page could not show.

- **index.html: Accessibility 92 -> 100, Agentic Browsing 67 -> 100, mobile
  Performance 95 -> 97, TBT 40ms -> 0, LCP 2.6s -> 2.0s.** Desktop LCP element
  render delay **1,018ms -> 146ms**, which is the `.reveal` diagnosis confirmed.
- **Mobile element render delay is still 2,000ms and is NOT yet explained.**
  Desktop fell 86%, mobile only 26%, so something else dominates under the 4x CPU
  throttle. Untested candidates, in order: `decoding="async"` on the LCP image
  (it permits the browser to paint without it), the `drop-shadow` filter on a
  600x600 alpha image, and the still-`.reveal` hero heading beside it. **Do not
  "fix" any of these without measuring first** - the last confident guess in this
  file cost a broken JS bridge.
- **SEO 100 -> 92 with `canonical` scoring 0 is a TEST-URL ARTIFACT, not a
  regression.** The run was on `https://canvasdownloader.app/index.html` while the
  canonical says `https://canvasdownloader.app/`, and Lighthouse fails a non-root
  page whose canonical points at the site root. The round-1 run on
  `canvasdownloader.app/` scored SEO 100 on the same markup. **Always test the
  homepage as `/`, never as `/index.html`.**
- **`link-in-text-block` failed on every article-shell page and the colour route
  is arithmetically dead.** `.art a` was `text-decoration: none` with underline on
  hover only, so at rest a prose link was distinguished by colour alone. axe needs
  **3.0:1 between the link and the surrounding TEXT**; measured `--cyan #38bdf8`
  against body `--txt2 #bfc3c9` is **1.21:1**, and no cyan reaches 3:1 (`#67e8f9`
  1.22:1, `#a5f3fc` 1.42:1) because both are light colours on a dark ground.
  Compute that ratio before proposing a colour tweak. Fixed with an underline
  scoped to `.art p a, .art li a`, with `.toc`, `.cta-row` and `.byline` opted
  back out: a TOC is a list of links, not a text block.
- **`target-size` failed on the compact footer, 19 pages.** 13px links with only
  `margin: 0 12px` gave a ~18px tall box against a 24px minimum. `display:
  inline-block; padding: 6px 0` takes it to 33px and moves no text. The big
  footer on index/guide/engine already passed, so the census is the RULE string,
  not the tag.
- **Three pages wrote their link rule three different ways** (`.art a { colour;
  text-decoration: none }` on the 13 articles, `.art a { colour }` on canvas-data,
  a bare `a { ... }` on the directory), so a single-string replacement would have
  reached 13 of 15. Same failure mode as the `nav .btn-nav-ghost span` sweep.

## `lastmod` is about the FILE; "Updated" is a claim to the READER (2026-08-31)
After a 27-page accessibility pass, `scripts/sync_sitemap_lastmod.py --write`
moved 24 sitemap entries to 2026-08-31 while every article still says *Updated 27
August 2026* in its byline and its JSON-LD `dateModified`. **That disagreement is
correct and must be left alone.**
- The change was `aria-label`s, a `<main>` wrapper, heading levels and a link
  underline. **Not one word of any article changed.** Bumping the visible byline
  would tell a reader the piece was revised when it was not, which is the same
  class of untruth as an invented install count.
- `dateModified` is what a search engine may print beside the result. Inflating it
  on a markup-only change is what trains an engine to stop trusting the field, and
  this site's measured constraint is already indexing rather than crawling.
- `lastmod` makes a different claim - this RESOURCE changed, so re-fetch it - and
  that is true. Google treats it as a hint and ignores it when it looks
  untrustworthy, so it is worth being able to say what actually changed.
- **The rule: bump the byline and `dateModified` only when the PROSE changes.**
  Markup, CSS and accessibility passes move `lastmod` alone.


## Run Lighthouse LOCALLY - it is the same binary PSI uses (2026-08-31)
`npx lighthouse@13.4.1` is the exact version PageSpeed Insights runs, so the
whole site can be measured in minutes instead of pasting URLs one at a time.
`--form-factor=mobile --screenEmulation.mobile --throttling-method=simulate`
reproduces the PSI mobile run: measured live index LCP 2218 ms against a local
2310 ms, within 4%. **In simulated mode it is deterministic** - n=3 gave spread
0 ms on every arm - so a difference of 300 ms between two arms is real and does
not need repeats to believe. Single runs are still worth repeating once, because
a stale working copy produces contradictions that look like effects.

- **A local static server is NOT the live site until it gzips.**
  `python -m http.server` sent index.html at **201 KiB where GitHub Pages sends
  48 KiB**, total transfer 732 KiB against 233 KiB. Under simulated slow-4G that
  is a different regime, and the first variant sweep ran entirely inside it: the
  control showed a 110 ms LCP render delay against the live 1985 ms, so every
  "no effect" result was worthless. A 30-line gzip handler fixed it and the
  control then matched live. **Check transfer size against the live page before
  trusting any local performance number.**
- **Serve from the PARENT of the copy under test.** With the server's cwd inside
  the directory, Windows refuses to delete it between runs (`WinError 32`), so
  the harness silently reused a stale tree.
- **The LCP SUBPART attribution does not survive the move to localhost, but the
  LCP total does.** Live attributed 1985 ms to element render delay; the local
  control attributed 110 ms with the same total, because the image is discovered
  instantly. Optimise against the total; read the subparts only on the live run.

## The 2s mobile render delay was mostly the FAVICON (2026-08-31)
`docs/icon.ico` was **370 KB** - six frames up to 256x256, larger than the entire
homepage document - and every one of the 27 pages requests it. Rebuilt at 16/32/48,
the only sizes a browser tab uses: **361 KiB -> 4.9 KiB, 98.6% smaller.**
Measured on the live headers: it is served `Cache-Control: max-age=600` WITH an
ETag, so the saving lands on a COLD CACHE - a first visit, or one after the file
was evicted. A returning visitor already revalidated to a 304 with no body and
sees no change. Lighthouse always models a cold cache, so its scores state the
best case; quote this one as a first-visit win, which is still the visit that
decides whether a new student stays. It was found by reading the network table of the WORST page
rather than the most important one: win-setup.html is a 6 KiB document that scored
77, and the favicon was sixty times the page.

- **`assets/icon.ico` at the repo root is a DIFFERENT file and must keep its large
  frames** - `Canvas_Downloader.spec` uses it for the executable, where Windows
  Explorer really does want 256x256. Only the `docs/` copy was shrunk.
- Mobile performance after, measured locally: guide **86 -> 100**, engine 88 -> 99,
  mac-setup 90 -> 99, blog 93 -> 100, canvas-data 93 -> 100, releases 81 -> 93,
  thanks-win 81 -> 94, win-setup 77 -> 90.
- **The other four candidates were all falsified.** Removing the hero
  `drop-shadow`, dropping `decoding="async"` and un-revealing the hero heading
  each moved index LCP by 1 ms or less once the harness was correct. Inlining
  `fonts.css` is the only other real one: **2310 -> 2010 ms, n=3, spread 0**, and
  it is NOT applied, because it would put 26 copies of the same `@font-face`
  block in 26 files, which is the drift this file's first entry exists about.
- **The hero `.reveal` fix DOES apply to guide and engine**, both of which opened
  with `<h1 class="reveal">` plus a revealed lede: guide LCP 4410 -> 4110, engine
  4260 -> 3810, render delay about -500 ms each, n=2 spread 0. engine.html now has
  ZERO `.reveal` elements and left `GATED_PAGES` in the no-JS test.

## Measure every page, because one page cannot show a class (2026-08-31)
PSI covered three pages. Sweeping all thirteen shapes locally found failures on
pages nobody had looked at, including two MISSES FROM MY OWN ROUND-2 FIXES:
`mac-setup.html` and `releases.html` write the footer rule multi-line, so a fix
keyed on the single-line string reached 19 pages and skipped those two. Third
time this exact shape appears in this file.

- **An opacity multiplier on top of `--txt3` is what fails colour contrast.**
  `guide.html` was the only page with `.foot-v { opacity: 0.45 }` and
  `releases.html` the only one with `opacity: 0.7` on the whole footer; every
  other page declares the token and stops. Both removed. `thanks-win.html` also
  carries `opacity: 0.6` and was LEFT, because its footer uses the brighter
  `--txt2` and it scores 100 - do not restyle a page that passes.
- **An inline `style="...text-decoration: none"` beats any stylesheet rule**, so
  the round-3 prose-underline rule did not reach two links on `win-setup.html`
  and `thanks-win.html`. Census the inline form separately: 19 exist across 6
  pages, and only the 3 inside prose needed changing - Lighthouse is the oracle
  for which ones are in a text block.
- **Result: Accessibility 100 on all 13 page shapes.** The remaining reported
  failures are all intentional or artefacts: `thanks-*` and `404` fail
  `meta-description` and `is-crawlable` because they are deliberately noindex and
  excluded from the sitemap, and `404`'s `errors-in-console` is the harness -
  that page uses ROOT-relative paths by design, so `/fonts.css` and `/icon.ico`
  404 when it is served under a subdirectory.

## Two diagnostics lied this session; both were caught by a control (2026-08-31)
Worth copying, because in both cases the RESULT looked clean and meant nothing.

- **The reveal test reported "no effect" while editing nothing.** It sliced the
  hero at the first `<div class="container">` after `</nav>`, but on guide and
  engine the `h1` is INSIDE that container, so the slice ended before it. Adding
  `assert removed == 2` turned a false negative into a real -300/-450 ms result.
- **A heredoc turned `\b` into a literal backspace, again.** The widened
  `_pages_using_reveal` regex compiled to `class="[^"]*\x08reveal\x08[^"]*"` and
  matched nothing, so the guard reported that NO page uses `.reveal`. This file
  already documents the hazard from 2026-08-28 and the rule was ignored anyway:
  **any payload containing backslash escapes goes through the file tools or a
  script FILE, never a heredoc.** Verified after the fix with a four-way control:
  matches a compound class and a bare one, rejects `revealed` and an unrelated
  class.
- **`_pages_using_reveal` had a latent defect of its own**: it matched the PREFIX
  `class="reveal`, so it only saw elements where `reveal` is the FIRST class.
  `guide.html` has 136 of the form `class="body-text reveal"` and, once its two
  prefix-matching elements were removed, the whole page dropped out of the census
  while 136 gated elements were still on it. A guard a class REORDER can switch
  off is exactly what its own docstring warns against. It is a token match now.
- **Playwright element screenshots come back BLANK here.** `locator.screenshot()`
  on a footer produced empty dark images on a page that renders correctly, and
  the control - the same capture on a page that had not been touched - was blank
  too. `elementFromPoint` confirmed the links were the topmost elements. Use
  viewport screenshots, and always capture an untouched page before believing a
  screenshot shows a regression.
