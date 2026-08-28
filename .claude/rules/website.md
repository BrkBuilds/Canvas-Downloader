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
`--rad-s: 5px`, identical everywhere, guarded per page by
`tests/test_website_reading_hygiene.py` (21/21 mutants caught).
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
Two checks in `tests/test_website_reading_hygiene.py` were written through a
shell heredoc and silently compiled to `outline:\s*(none|0)\x08` - a pattern
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
  page change. `tests/test_sitemap_lastmod.py` fails when any entry is older than its file's last
  commit, and also when a `<loc>` has no file behind it, which is a 404 announced to two engines.
- **The test skips rather than fails when git history is absent.** CI clones with
  `fetch-depth: 1` by default, where `git log` for a path is legitimately empty; a guard that
  cannot see history must say so instead of reporting all 22 pages as stale.
- Mutation-checked three ways: a reverted date, a deleted `<lastmod>` tag, and a `<loc>` pointed
  at a file that does not exist. All three fail as they should.
