# The blog: verdict, evidence, and the plan

Written 2026-08-26, against the five articles published 20 and 23 August 2026.
Read [STRATEGY.md](STRATEGY.md) first - its settled decisions bind everything
below, in particular the vocabulary rule and **the four-item nav**. Read
[FINDINGS.md](FINDINGS.md) before investigating anything here; the indexing
question is already answered there and must not be re-derived.

---

## 1. The verdict, in one page

**The articles are not lackluster. They are good prose aimed at the wrong
targets, carrying none of the signals that make a young domain rank or get
cited, sitting behind an internal-linking wall of the site's own making.**

Three separate problems, and only one of them is about writing:

1. **Target selection.** Three of the five compete for queries whose SERP is
   100% the reader's own institution. Those cannot be won by anyone, at any
   quality, on any domain. Measured below.
2. **Signals.** Every article has **zero outbound citations** and **zero to one
   statistic**. Those are the two content attributes with the largest measured
   effect on being cited by generative engines, and the effect is largest
   precisely for pages that do not already rank. Measured below.
3. **Discoverability.** `blog.html` is linked from the homepage **once, at 93%
   page depth, in the footer, and is in no navigation**. Three of the five
   articles have **no homepage link at all**. This is the exact defect
   `FINDINGS.md` diagnosed for the articles in August - footer-only linking is
   the weakest internal signal there is - now recurring one level up, in the hub
   that was built to fix it.

**Nothing on the site is built to earn a link**, which is the other half of the
stated job. How-to articles are ranking assets. They are not linking assets, and
Ahrefs' figure for how much published content earns zero external backlinks is
**94%**. A page that explains a procedure is a page a reader uses and leaves.

### Do NOT scrap them

Scrapping is the most expensive available way to fix a set of cheap problems.

- The prose is **better than what currently ranks**. `leadde.ai` holds a
  page-one slot for the video query with ~2,200 words of heavily promotional
  copy, no citations and no original data. Our flagship is more honest and more
  useful than that today. Quality is not the binding constraint.
- The **fact-checking is banked and expensive**. Two misconceptions were
  corrected during grounding (students cannot export a course; the submissions
  export excludes annotated versions) and are stated on the page. That research
  is the asset, not the HTML around it.
- **Killing URLs resets discovery.** Google had crawled at least one of these
  three days before this was written. Redirect churn on a domain with no
  authority buys nothing.
- The pages are **generated** (`scripts/guide_pages_content.py` +
  `build_guide_pages.py`), so a defect fixed in the template lands on all five
  and on every future one. The unit of repair is the generator, not the article.

**The correct move is: repair the five, fix the linking, then add the four to
six pages the demand data says are missing, and build the one asset that can
actually earn a link.**

---

## 2. What was measured

All of it re-measurable from the repo and a browser. Date 2026-08-26.

| Article | Words | Outbound citations | Statistics | Visible byline | Visible date |
|---|---|---|---|---|---|
| `how-to-download-all-canvas-files` | 2,150 | **0** (1 self-link to GitHub) | 1 | no | no |
| `canvas-access-after-graduation` | 1,447 | **0** | 0 | no | no |
| `download-panopto-lecture-recordings` | 1,550 | **0** (1 self-link) | 0 | no | no |
| `save-canvas-assignment-feedback` | 1,615 | **0** | 1 | no | no |
| `canvas-files-into-notebooklm` | 1,626 | **0** | 9 | no | no |

**The flagship quotes the Instructure Community and does not link it.** The
sentence *"As for Pages and Assignments, I'm not sure of a quick way off the top
of my head"* is on the page as evidence, unattributed by URL. That is a citation
already written and then thrown away.

**Internal linking, position as a percentage of `docs/index.html`** (measured
on the newline-normalised text, so it is a character offset rather than the
raw byte count `wc -c` reports):

| Target | Homepage links | Position |
|---|---|---|
| `how-to-download-all-canvas-files.html` | 1 | 93% |
| `canvas-access-after-graduation.html` | 1 | 93% |
| `blog.html` | 1 | 93% (footer nav) |
| `download-panopto-lecture-recordings.html` | **0** | - |
| `save-canvas-assignment-feedback.html` | **0** | - |
| `canvas-files-into-notebooklm.html` | **0** | - |

**Schema:** all five carry `Article` + `FAQPage` + `BreadcrumbList` + `Person`.
Correct, and one part of it is now inert - see the FAQ note in section 3.

**Competitive traction, GitHub API, 2026-08-26:**

| Repo | Stars | Created |
|---|---|---|
| `jasp-nerd/canvas-course-downloader` | **37** | 2026-03-07 |
| `RoryQo/Canvas-Course-Downloader` | 22 | 2025-04-22 |
| `aik2mlj/canvas-downloader` | 9 | 2025-10-02 |
| `jamubc/Canvas_Downloader` | 5 | 2025-12-06 |
| **`BrkBuilds/Canvas-Downloader`** | **2** | 2026-01-17 |

`jasp-nerd` is the one to watch. It is five months old, it ranks **#2** for the
NotebookLM query, and its GitHub description is written for that query:
*"exporting course materials to feed into AI tools like ChatGPT, NotebookLM, or
Claude."* It is out-positioning us on the one moment `STRATEGY.md` already
identifies as the least contested.

### The SERPs, measured

Searched 2026-08-26. **Caveat, stated because it matters:** these were run from
a Norwegian IP with US targeting requested, and geo leakage was observed in the
autocomplete data (`panopto uib`, `panopto ntnu`). Treat ordering as indicative
and the *composition* of the result set as reliable.

| Query | What holds page one | Winnable? |
|---|---|---|
| how to download all files from canvas at once | Illinois, NCTC, Stanford, Clemson, Brown, Minnesota, Instructure Community, **one Chrome extension sharing our name**, one content-farm blog | **Partly.** Two non-`.edu` slots exist and one is already taken by a blog |
| canvas access after graduation | Michigan, HWS, Stanford, Northwestern, Penn, USNH, WashU, Penn Nursing, LPS. **Ten of ten institutional** | **No.** The true answer is per-institution, and the reader's own university outranks everyone for their own reader |
| how to download panopto lecture recordings | Boston College, Stanford, Pitt (x2), Cambridge, Southeastern, Notre Dame, Washington, UCL. **Nine of nine institutional** | **No, as framed.** See the retarget in section 5 |
| how to get canvas files into notebooklm | Obsidian plugin, **`jasp-nerd` GitHub**, LinkedIn Pulse, BYU-I, **two TikTok pages**, Instructure Community, Instructure blog | **Yes.** Weakest SERP of the five by a wide margin |
| save canvas assignment feedback | Mixed intent, mostly instructor-facing, no page matching the query | **Unclear.** Google cannot find a good match, which is either a gap or an absence of demand |

**The pattern is the finding.** A query whose honest answer is *"it depends on
your university"* is permanently owned by universities. A query whose honest
answer is the same for everyone is open. Two of the five articles are on the
wrong side of that line and no amount of rewriting moves them.

---

## 3. What the research says

### Citing sources and quoting is the single largest lever available to us

The Princeton / IIT Delhi GEO study tested nine content modifications against
generative engines and measured the visibility change:

| Method | Measured effect |
|---|---|
| Quotation addition | **+28% to +41%** |
| Statistics addition | **+33%** overall, +37% on Perplexity |
| Cite sources | strong, and **+115% for a page sitting at position 5** |
| Fluency optimisation | positive |
| **Keyword stuffing** | **-10%, worse than doing nothing** |

Two things follow, and they are the reason this section leads.

**First, the effect is largest for pages that do not already rank.** That is
precisely our position. A high-authority page gets cited because it is
high-authority; a low-authority page gets cited because it is *verifiable*, and
citations are how a machine verifies.

**Second, we are at zero on all three of the winning methods and we already own
the material.** The Instructure Community quote is on the page. Instructure's
own documentation says what Canvas exports and does not. The app's audit history
contains real measured numbers. Nothing here requires new research, only linking
what was already read.

### FAQ rich results are gone, and the markup should stay anyway

Google put a deprecation notice on the FAQ structured data documentation on
**7 May 2026**; the search-appearance filter, the Search Console report and Rich
Results Test support were removed in June 2026, and the API data in August 2026.

**Keep the markup.** It costs nothing, unused structured data does not affect
Search, and the question-and-answer shape is still what a generative engine
extracts. What must change is the expectation: it is no longer a visibility
feature, so it must not be treated as one when deciding whether a page is done.

### AI answers are now a first-class destination, not a side channel

AI Overviews appear on an estimated 30 to 40% of queries. The audience matters
here more than the average: a student searching *"how do I get my Canvas files
into NotebookLM"* is by definition already using AI tools, and is
disproportionately likely to ask the assistant rather than the search box.

`docs/llms.txt` already exists and is the right instinct. The gap is that the
*articles* are not written to be quoted - no statistics, no citations, and no
extractable one-sentence answers under the headings.

### Reddit takes the slots we would otherwise compete for

A Search Engine Land analysis of 10,000 product-review keyphrases found Reddit
present in **97.5%** of them, taking roughly two thirds of Google's
"Discussions and forums" slots. Autocomplete confirms students do this
deliberately: **`download canvas videos reddit`** is a suggested query.

**The strategic reading is not "give up on the blog".** It is that the blog's
job includes being *the page a good Reddit comment links to*. That makes
`PLAYBOOK.md` section 5 and this plan one piece of work rather than two. A
comment that answers a question and links a page answering it more fully is the
cheapest backlink available to a project like this, and the only one that scales
honestly.

### Google's own bar, quoted

From *Creating helpful, reliable, people-first content*: content should make it
*"self-evident to your visitors who authored your content"*, with bylines that
*"lead to further information about the author"*, and should demonstrate
*"first-hand expertise ... that comes from having actually used a product"*.

We have the rarest form of that - the author built the engine and has measured
its behaviour against real courses - and the articles show none of it. There is
no byline, no date, and no first-person evidence on the page.

---

## 4. The demand map

Pulled 2026-08-26 from Google's autocomplete endpoint (`suggestqueries`,
`hl=en`, `gl=us`) across twenty-seven seed stems. This is a *relative* demand
signal, not volume: a suggestion exists because people type it. Geo leakage was
present, so treat non-English-market institution names as noise.

**Cluster A - lecture video. The largest cluster, and we have one page on one
sub-case.**

```
how to download canvas videos          <- top suggestion for "how to download canvas"
how to download canvas lecture videos
how to download canvas studio videos
canvas download embedded video
canvas download video from media gallery
canvas download video submission
canvas download video transcript
download lecture videos from canvas
download lectures from canvas
download lectures from echo360
download canvas videos reddit
```

**Cluster B - Panopto transcripts. Narrow, uncontested, and we are the only tool
that produces them.**

```
panopto transcript download
panopto download transcript student
panopto export transcript
panopto lecture transcript
panopto download captions
panopto transcript generator
panopto downloader chrome extension
```

**Cluster C - "all / entire / bulk", the flagship's own cluster.**

```
download all canvas files
download all canvas courses
download all canvas content
download all canvas modules
download entire canvas course
canvas download course content student
canvas files downloader
backup canvas course
archive canvas course
```

**Cluster D - single content types Canvas has no bulk export for. Each is a
narrow, low-competition query, and the app already produces every one of them.**

```
canvas download quiz as pdf
canvas download quiz questions
download canvas quiz to word
canvas download discussion posts
canvas download all discussion posts
download canvas page as pdf
how to download canvas syllabus as pdf
canvas download announcements
canvas download assignment with annotations
canvas download assignment with comments
```

**Cluster E - the access token. Our own setup requirement is a searched topic.**

```
canvas access token
canvas personal access token
canvas generate access token
canvas access token url
canvas expired access token
```

**Cluster F - finding your Canvas URL.**

```
find my canvas url
find my school canvas
find my school canvas login
find my institution canvas
canvas url search
canvas url search tool
```

### Three readings that change the plan

1. **Video is the biggest miss.** It is the top autocomplete completion for the
   most obvious stem, it recurs across four separate seeds, and its SERP is the
   least institutional of any measured - two content-farm blogs hold slots. We
   have one article, on Panopto, framed around a permission question.
2. **Cluster D is the product's actual differentiator and has no page at all.**
   *"canvas download quiz as pdf"* and *"canvas download all discussion posts"*
   describe things Canvas cannot do, that this app does, and that no `.edu` page
   can answer with anything but "you cannot". These are small queries. They are
   also unloseable, and each converts at close to 100% because the only honest
   answer is a tool.
3. **Cluster E is the highest-intent traffic on the list.** Someone searching
   *"canvas personal access token"* is mid-setup. It is also where the trust
   story belongs, and `STRATEGY.md` says trust must lead.

---

## 5. The plan

Ordered by expected value per hour. Phase 0 and 1 are cheap and land on every
article at once; do not start Phase 2 before they are done.

### Phase 0 - repair the generator, once. DONE 2026-08-27

Measured before and after, on the five built pages:

| | Before | After |
|---|---|---|
| Outbound citations to primary sources | **0** across all five | **19**, 3 to 5 per page |
| Statistics per article | 0 to 1 (9 on one) | 4 to 18 |
| Visible byline | none | all five |
| Visible published / updated date | none | all five |
| Author box | none | all five |
| Short-answer block | none | all five |

**Every citation URL was fetched and returned 200 before it was used**, and
the three Instructure KB articles were checked by page title so the right
article is attached to the right claim. Two guessed Panopto support slugs
404'd on that check, which is the whole argument for doing it: a dead
citation is worse than no citation, and it is invisible in review.

**The sources were already known.** The grounding docstrings in
`guide_pages_content.py` named Illinois KB 127046, Stanford 115001602467,
NCTC 205334770, Instructure Community 618390 and Instructure KB 661234 /
661231 / 661230 from the day the pages were written. The research had been
done and simply never reached the page - so this was not new work, it was
publishing work already paid for.

Every item lands on all five existing articles and every future one.

1. **Add outbound citations, and make them a rule.** Minimum three per article,
   to primary sources: Instructure's own documentation, the Instructure
   Community thread being quoted, Google's NotebookLM help, Panopto's docs. The
   flagship's existing unattributed quote is the first one to fix. Measured
   effect is the largest single lever available to a page in our position.
2. **Add a visible byline and a visible "Last updated" date.** Google's own
   guidance asks for it by name. The dates already exist in `PAGES`; they are
   rendered on the index and not on the article.
3. **Give the byline somewhere to lead.** A short author box - who built this,
   that they wrote the engine, links to `engine.html` and to GitHub. `about`
   does not have to be a page; a component in the article template is enough.
4. **Add a "short answer" block under each `h1`.** Two to three sentences that
   answer the title question completely. This is the block an AI Overview lifts
   and the block a skimmer needs, and neither currently exists.
5. **Put statistics in.** Every claim that can carry a number should carry one.
   See Phase 3 for where original numbers come from.
6. **Keep the FAQ markup, stop counting it as visibility.**

### Phase 0b - the CTA boxes, DONE 2026-08-26

All five were rewritten in the same session this plan was written, because the
product owner read them and the defect was worse than anything else on this
page. They were not weak by accident; they were written by someone applying the
honesty rule to the wrong element.

**What was wrong, in the words that found it.** The NotebookLM box said the app
*"pulls a whole course down in one run"* (no reader is impressed by one course),
listed *"Canvas Pages to Markdown"* (no student has ever wanted that sentence),
said *"lecture recordings"* where the reader's word is **Panopto**, described
the output as *"close to a list of what NotebookLM accepts"* when the app ships a
built-in preset **literally named `100% AI & NotebookLM Ready`** - and then
finished with *"You do not need it. If your course keeps everything in the Files
tab, Canvas will zip it and that is genuinely simpler."*

That last sentence is the whole lesson. It is **true**, it is **already stated
in the article body**, and putting it inside the conversion box meant the final
thing a reader saw before the Download button was an argument against pressing
it.

**The four rules, now applied to all five boxes:**

1. **The box is the conversion element. Limits go in the body.** `STRATEGY.md`
   says state limits in the same breath as claims, and that is right - the body
   is where the claim is made. Repeating the limit inside the CTA is not extra
   honesty, it is the same honesty in the one place it costs a download. Every
   limit removed from a box in this pass was already stated in the article
   above it; nothing was deleted from any page.
2. **Say the biggest true thing.** "One run" understated "every course you tick".
   The scale claim is the product, and four of the five boxes were hiding it.
3. **Use the reader's noun.** *Panopto lecture recordings*, not *lecture
   recordings*. *PowerPoints, Word documents and spreadsheets*, not *Office
   files*. Cut conversion mechanics the reader has no stake in - nobody wants
   Markdown, they want the file to be accepted by the thing they are uploading
   to.
4. **The box must answer THIS article's problem.** The download-methods box said
   only "free and open source, nothing uploaded" - a trust blurb with no
   capability in it, after 2,150 words that had established the capability.

**Match the ghost button's destination to its label.** All three "See how it
works" buttons pointed at `guide.html`, which is dense reference documentation
written for people who already run the app. A first-time reader who presses it
lands in a manual. They now read **"See it in action"** and point at
`index.html#features`, which is where the six demo clips are. Same fix, stated
generally: **a CTA sends an arrival to a page built for arrivals.**

**The miss underneath all of it:** an article about NotebookLM did not mention
that the product has a one-click NotebookLM preset. Before writing a CTA, read
`core/preset_manager.py` and check whether the app already has a named feature
for the exact job the article describes.

### Phase 1 - fix the linking, once. DONE 2026-08-27

Homepage links into the blog cluster, by page depth:

| Article | Before | After |
|---|---|---|
| `how-to-download-all-canvas-files` | 1, at 93% | 2, at **50%** and 93% |
| `canvas-files-into-notebooklm` | **0** | 1, at **60%** |
| `download-panopto-lecture-recordings` | **0** | 1, at **68%** |
| `save-canvas-assignment-feedback` | **0** | 1, at 93% |
| `canvas-access-after-graduation` | 1, at 93% | 1, at 93% |
| `blog.html` | 1, at 93% | 2, at 93% |

Cross-links between articles went from 1 to 2 each, to 2 to 3 each.
`guide.html` gained its first two contextual links, at 45% and 48% depth.

**THE TRAP, and it would have made the whole phase pointless.** Both
`index.html` and `guide.html` declare `a { color: inherit; text-decoration:
none; }`, so a plain `<a>` in body copy renders as **ordinary text**. Every
new link had to carry the inline style those pages already use for in-copy
links (`color: var(--cyan)`), or it would have been invisible, unclickable in
practice, and passing the internal-link test suite the entire time. Found in
the browser, not in review. Any future link into body copy on a
hand-maintained page needs the same treatment.

The hub was built to solve footer-only linking and is itself footer-only linked.

1. **The nav is not available and must not be asked for again.** Four items,
   permanently, settled by the product owner: How to set up, How It Works,
   Download, GitHub. This is the constraint the rest of Phase 1 is written
   around, not an obstacle to route past. Every link below therefore has to do
   real work, because there is no navigational shortcut to fall back on.
2. **Link every article from the homepage, in context, near the section it
   belongs to** - not in a single sentence at 93% depth. The Panopto article
   belongs beside the Panopto feature copy; the NotebookLM article beside
   whatever mentions AI tools.
3. **Cross-link the articles to each other in the body text**, three to five
   contextual links each, with descriptive anchors. Several already do this
   once; make it the rule, and make the anchor text the target query.
4. **Link from `guide.html`.** It is 126 KB, it is indexed, and it currently
   links the blog only from its footer. It is the strongest internal page we
   have to pass authority from.

### Phase 2 - the articles to add, in order

Six pages, each answering a question none of the others answers, and each
justified by a distinct autocomplete cluster in section 4. The count comes from
the demand map and nothing else: these are the clusters with evidence behind
them. **A seventh needs a seventh cluster**, not an argument about whether more
pages are good.

| # | Working title | Cluster | Why now | Status |
|---|---|---|---|---|
| 1 | How to download lecture videos from Canvas | A | Biggest measured demand; least institutional SERP; currently answered by two content farms | **DONE 2026-08-27** |
| 2 | How to get a transcript of a Panopto lecture | B | Uncontested, and the only tool that produces one is ours | **DONE 2026-08-27** |
| 3 | How to save Canvas quizzes, pages, discussions and announcements | D | The differentiator, with no page at all; every query in the cluster resolves to "Canvas cannot" |**DONE 2026-08-27** |
| 4 | What a Canvas access token is, and what it can and cannot do | E | Highest-intent traffic; the natural home for the trust story |**DONE 2026-08-27** |
| 5 | Canvas Downloader vs the Chrome extensions vs the scripts | - | Captures `canvas downloader extension` and `canvas course downloader github`; `STRATEGY.md` already requires this comparison be made, fairly |**DONE 2026-08-27** |
| 6 | How to back up a Canvas course before you lose access | C | Absorbs `backup / archive canvas course`, and gives the graduation article something to become |**DONE 2026-08-27** |

#### Article 5, shipped 2026-08-27

`docs/canvas-download-tools-compared.html`, 2,353 words, 3 citations, all to
competitors' own repositories.

**The conflict of interest is disclosed in the second section, under the heading
"Who wrote this", before any comparison happens.** A comparison page written by
one of the competitors is worth nothing unless it says so before the reader
works it out. It then has to behave accordingly, so **three of the five
recommendations in "which one you should actually use" point somewhere other
than this app** - Canvas's own Download as Zip, a browser extension, and a
script, each with the situation that makes it the right answer.

**Every claim about another tool comes from that tool's own documentation, with
a link.** That is what makes the page defensible and it is also what made it
useful, because reading their docs properly changed what I could honestly
claim.

### It corrected STRATEGY.md, which was verified 2026-08-20 and is now stale

The competitor table says browser extensions *"Work per page not per account; no
'all courses'; no memory between runs"*. **jasp-nerd's extension does all
three**: it selects multiple courses from the dashboard, and it has an
*"Incremental mode [that] skips files you've already downloaded on previous
runs"*. So **two of the three things STRATEGY.md calls "the three things no
competitor combines" are matched by one free extension**, and it needs no access
token at all because it rides your browser session.

That advantage is *growing*, not shrinking, because of what article 4 documents:
Canvas keeps shortening token life. An extension sidesteps the whole problem.

**What survives as genuinely ours**, checked against their own words:

| | Evidence |
|---|---|
| Panopto recordings | jasp-nerd: *"Content hosted by third-party LTI tools (Turnitin, Panopto, external videos) lives outside Canvas and can't be downloaded"* |
| Quiz questions | davekats: the tool *"cannot capture quiz data"* |
| Conversion as it downloads | No competitor offers it |
| Edit protection on re-sync | No competitor offers it |

**Scale is reported even though we lose it.** Checked via the GitHub API:
davekats **265** stars, jasp-nerd **38**, kas **14**, jamubc **5**, this project
**2**. The page prints that, notes stars are a poor proxy for a desktop app
shipped through an installer and the Microsoft Store, and then tells the reader
to use **last-updated date** as the signal instead - because one popular script
in that list has not been touched since **December 2023**, and Canvas has
changed its token rules twice since.

### It also caught a real error in article 4, published two hours earlier

Article 4's "if your university has switched tokens off" section said *"no tool
can work around it"* and then listed only Canvas's built-in routes. **Browser
extensions need no token**, so they work fine, and that sentence cost the reader
a genuine option. Corrected to "no API-based tool", with the extension route
named and linked. Worth noting the shape: **writing the comparison is what
audited the earlier page.** Neither the tests nor a re-read would have found it.

### Measured against the writing targets

Best-in-class on the two axes section 10 tracks: **24% short sentences** (the
highest of the ten) and **2% long ones** (the lowest), at 0.6 dashes per 1k
words.

The scanner flagged three anaphora runs. All three were deliberate parallel
enumeration of the three tool shapes, which is what parallelism is *for* - but
two of them were near-identical to each other, one in the short answer and one
in an FAQ answer, so the FAQ was rewritten. **A flag can be correct about the
pattern and wrong about the verdict; the useful part was noticing the
duplication underneath it.**

**The scanner's negation check was also wrong and is now fixed.** It fired on
four articles and three were false positives - it matched *across full stops*,
pairing clauses from different sentences, and it counted ordinary compound
clauses ("this is not rare **and** it is worth checking") as contrastive
negation. Tightened to require a comma or dash and no coordinating conjunction,
with a six-case positive/negative control in the commit. Across all ten articles
the count went 4 -> 1, and the one real hit was rewritten. **Second time in this
session a checker needed fixing before its number meant anything.**

#### Article 5, REVISED the same day after product-owner review

The first version was accurate and under-sold the app, which is its own kind of
dishonesty on a comparison page. The note, verbatim in substance: the other
tools are much closer to Canvas's own zip export wrapped in a different
package; a CLI is not built for a non-technical student and a Chrome extension
is built to be temporary; Canvas Downloader is a resident application meant to
accompany a student through a whole degree.

**The fix was structural, not a longer feature list.** The article now argues
from SHAPE, and everything else falls out of it:

| Shape | What it is built to be |
|---|---|
| Browser extension | a button - exists while the popup is open, then gone |
| Script | something you run, from a terminal, that stops when it finishes |
| Desktop app | installed - keeps a record, runs on a schedule, reaches local software |

Then one distinction the article turns on, in a new section: **are you taking a
snapshot, or keeping a folder current?** Every tool does the first. The second
is a different question and it is where the app's own features stop being a
list and start being an argument. New subsections cover Analyze, Review & Sync
(the review screen with its five categories, nothing written until you press
the button), Quick Sync, Today's files, conversion so the folder is
drag-and-drop ready for AI study tools, and edit protection.

**The stars/installs comparison was reframed rather than softened.** davekats
has 265 GitHub stars and this has 2. The article prints that, then says what
each number counts: a star is a developer bookmarking a repository, and nobody
stars an app they installed from the Microsoft Store. Against 2 stars the app
has 900+ installs. Both numbers, the reader draws the conclusion.

Word count 2,361 -> 3,791. Measured after the rewrite it is still the best page
on the site for the two tracked axes: **26% short sentences, 3% long, 0.0
dashes per 1k**. The scanner found three anaphora runs and two were rewritten;
the surviving one is the definitional "A browser extension / A script / A
desktop app", which is the only place the three shapes are named side by side
and where the parallel form is what makes it scannable.

**900+ replaced 800+ on the homepage and in llms.txt in the same pass.** The
figure is a lifetime cumulative total rounded down with no as-of date
(`FINDINGS.md`), so it can be raised whenever the floor moves, and an article
quoting 900 beside a homepage saying 800 is a defect either way.

**A blind spot in `scripts/check_ai_writing_tells.py`, found while verifying
this.** It extracted the prose with `<article>...</article>`; the generated
pages use `<div class="art">`, so the match failed on every page and it
silently fell back to scanning the whole document. It survived because the
shell contributes almost no `<p>` and because the FAQ truncation removed the
footer as a side effect. Correct by accident. `_body()` now raises rather than
falling back. Re-measuring moved every number by at most one point, so no
earlier conclusion changes - but a guard reading a superset of what it claims
to read is the same defect class this repo keeps finding.

**Harness trap worth knowing: `browser_resize` did not reflow the layout
viewport.** A "no horizontal overflow at 390px" check was actually taken at
2560px and proved nothing. Constrain the container in JS and measure, or check
`window.innerWidth` before believing a width-dependent result.



#### Article 4, shipped 2026-08-27

`docs/canvas-access-token-explained.html`, 2,425 words, 5 citations.

**The spine is one sentence from Instructure**, and it answers the only question
a nervous reader actually has: a token *"allows the access token holder to
access the same Canvas resources that you can access"*. The same resources.
Nothing extra. Everything else on the page hangs off that.

**The research found current facts that nothing published has**, from
Instructure's own product blog: administrators have been able to block student
token creation since September 2025; every token has needed a stated purpose
since October 2025; and the July 2026 update cut the maximum life again.

**Do not restate the headline numbers as fact - they are role-dependent.** The
product owner checked their own account mid-write: it offered **90 days**, not
the 30 Instructure's post gives for students, having previously offered 120. The
mechanism is in the same post and it is about ROLES, not institutions - the
short cap binds *"users with only student roles"*, and a longer life *"can be
achieved by giving the user any role other than student (even with all
permissions locked down)"*. A TA enrolment or a designer role on one module is
enough. The page therefore says the settings page is the only authority on your
own number, which is both more accurate and more useful than the announcement.

**The policy line is faced head-on, in its own section.** Instructure's own KB
says *"It is a violation of Canvas API policy for a user to generate an access
token to insert into an application."* That covers what this app asks people to
do. Burying it would be the worst available choice on a page about trust, and a
reader who finds it elsewhere afterwards has been handed a reason to distrust
everything else here. So the page quotes it, then gives the structural reason it
cannot simply be complied with: Canvas's API docs say *"developer keys are
issued by the admin of the institution"* and are scoped to it, so an independent
tool would need one from every university separately. Then three rules, the
first two of which point AWAY from this app - use your institution's approved
route if it has one, and treat student tokens being switched off as the answer
rather than an obstacle.

**One first-hand claim, stated as checkable**: the app performs zero HTTP writes
against Canvas. Verified by grep across `core/`, `sync/`, `ui/`, `shared/`,
`engine/` and `app.py` - nothing outside the Panopto LTI handshake.

### THREE STALE CLAIMS ON THE LIVE SITE, found by this research and fixed

Not blog defects. Product-facing instructions that Canvas had made wrong:

| Page | Said | Reality |
|---|---|---|
| `guide.html` | *"leave the expiry blank"* | Canvas now requires an expiry, and a purpose |
| `win-setup.html` | *"you never do this again"* | Tokens now expire; you do it again |
| `mac-setup.html` | (no mention of expiry) | Same |

All three now say an expiry is required without naming a number, since the
number is role-dependent. Note the likely origin of the first one: **Canvas's
own KB video still demonstrates the blank-expiry flow.** Instructure's docs
contradict Instructure's product, and the site inherited the error.


#### Article 3, shipped 2026-08-27

`docs/save-canvas-pages-quizzes-discussions.html`, 2,503 words, 5 citations.

**The research overturned the premise of this row, and improved it.** The plan
said "every query in the cluster resolves to *Canvas cannot*". Canvas **can**,
and students **can**: there is an **Export Course Content** button on the
**Modules** page that packages a whole course as browsable offline HTML, and
Instructure documents it for students specifically (KB 661316). Almost nobody
knows, for two good reasons - it is an administrator setting that is absent at
many institutions, and it lives on the Modules page, which is not where anyone
looks for a download.

So the page leads with it, the same call as article 2 leading with Panopto's own
transcript. **Then Instructure's own documentation of its limits turns out to be
exactly this cluster**, in their words:

- *"Discussions and quizzes only include the description."*
- *"All discussion replies (graded or ungraded) are considered submissions and
  must be viewed online."*
- *"Content items locked by modules or by date are not included in offline
  content."*
- *"Offline downloads include all content from the course at the time of the
  download."*

**The single most actionable sentence found anywhere on this site is in that
article**, and it is why the section is titled *The one built-in route, and its
expiry date*:

> *"Offline content cannot be downloaded once a course is concluded."*

The only built-in route to this material **closes at exactly the moment people
go looking for it**. That is a genuine, dated, citable reason to act now, it is
not a sales argument, and no competing page states it.

Two further findings the page rests on:

- **The complete export exists and needs a teacher role.** The `.imscc` package
  contains the whole course - settings, syllabus, modules, assignments, quizzes,
  **question banks**, discussions, pages, announcements, rubrics, files, calendar
  events. That single fact explains most of the confusion in this cluster: every
  guide describing it was written for somebody with different buttons. The page
  says asking a lecturer is a one-minute favour rather than a lost cause.
- **Quizzes are the urgent case, and the reason is a setting.** *Let Students
  See Their Quiz Responses* has an option called **Only Once After Each
  Attempt**, under which (Rice University's Canvas guidance) *"Students will only
  be able to view the results immediately after they have completed the quiz"*.
  Once, ever. So the page's rule is blunt: if a quiz and your answers are on
  screen, that may be the only time they ever will be.

**Scope stated in the body, not the box**, per Phase 0b: the app fetches
**Classic** Quizzes, and New Quizzes is a separate Instructure product delivered
as an external tool and is not covered. Also stated: the app can only save what
your account is allowed to see, which is the correct behaviour and worth saying
out loud on a page about restricted content.

**Instructure's own user guidelines are quoted rather than paraphrased** -
*"you may not reproduce or communicate any of the content in the course,
including exported files, without your institution's prior written permission"* -
and framed as a rule about sharing rather than about saving, which is what it
says.

**Linking**: five contextual inbound links (homepage pillar 1, the flagship, the
graduation article twice, the feedback article) and three outbound. The
graduation article gets two because both of its own list items - *announcements
and discussions*, and its closing *"the only way to get the categories Canvas has
no export for"* - were already describing this page without being able to point
at it.

**Verified in the browser**: 9 sections, 8 FAQ entries, CTA contrast 4.95:1, no
overflow at 390px (375 against 390), byline stacking on mobile.


#### Article 2, shipped 2026-08-27

`docs/panopto-lecture-transcript.html`, 2,959 words - now the longest page on
the site, and by a wide margin the most data-dense: **44 numeric facts and 6
citations**. This is the split section 6 asked for: PAGE 3 keeps the
permission-and-download story, this page takes the transcript half.

**It leads with Panopto's own transcript, not with ours.** That is the
`STRATEGY.md` fairness rule applied where it costs something - the free route
needs no software, is already there for most readers, and is simply the correct
advice for the majority. The app appears once the free route runs out, against
four named situations where it genuinely does.

**The research turned up a current, dated fact that changes the advice**, and
almost no existing guide has it. Panopto captions are moving to **on by default
for new content**, driven by accessibility law rather than a product roadmap -
Brown University's IT knowledge base dates it *"on or before May 11, 2026"* and
names the HHS Section 504 ruling and WCAG 2.1 Level AA. **Attributed to Brown
rather than stated as universal**: tenants are configured independently, and a
second institution (Boston College) documents the behaviour without the date.
So the page says "check yours", and says why the direction is one way.

The second useful finding is one the whole cluster rests on: **captions are
usually a separate permission from the video**, so they are frequently available
when downloading is not. That was already the best insight in article 1; here it
is the premise.

**The strongest asset on this page is first-hand measured data, and it is
better than what Phase 3a proposed.** `panopto/models.py` carries a real
measurement nobody outside this repo has: six speech models on the same clip,
timed as multiples of realtime.

| Model | Size | Speed on that CPU | One hour of lecture |
|---|---|---|---|
| Tiny | 75 MB | 25.5x | ~2 min |
| Base | 145 MB | 17.5x | ~3 min |
| Small | 484 MB | 6.2x | ~10 min |
| Large v3 Turbo | 1.6 GB | 3.3x | ~18 min |
| Medium | 1.5 GB | 2.5x | ~24 min |

And the finding that **corrects a claim repeated everywhere**: "use Large v3
Turbo, it is nearly as accurate and several times faster" is a **GPU fact that
does not transfer**. Turbo is fast because its *decoder* has 4 layers against
large-v3's 32 - but its *encoder* is large-v3's, unchanged, and on a CPU the
encoder dominates. So on a laptop it lands between Small and Medium, in the
group too slow to be practical. Real cost, from a real course: **36 recordings
that take 40 to 60 minutes on Tiny would have taken about 6.5 hours** on the
model a naive "pick the best" rule selects.

**The sample is stated honestly and prominently**, per section 5: one machine,
one 180-second clip, named settings, in a call-out headed *"The method, and how
small the sample is"*. A number presented as a benchmark it is not would not
survive this project's own rules - and the ordering is what is useful anyway.

**Two corrections were made to my own draft before it shipped**, both about not
overstating a measurement: Large v3 was never actually timed on that CPU (the
requirements table simply refuses it), so its row reads *"not timed - wants a
GPU"* rather than asserting a result; and the method note says "running on the
CPU" rather than "no GPU used", which the source comment does not establish.

**Linking**: five contextual inbound links - homepage pillar 6, plus the
graduation, Panopto, NotebookLM and lecture-video articles, each placed in the
paragraph that already argued for a transcript without saying how to get one.

**Verified in the browser at 390px**: the four-column table scrolls inside its
own box (640px table in a 327px wrapper, `overflow-x: auto`) while the page
itself does not overflow - 375 against a 390 viewport. Blog index at 7 cards,
newest first.


#### Article 1, shipped 2026-08-27

`docs/download-lecture-videos-from-canvas.html`, 2,673 words - the second
longest page on the site. Live in `sitemap.xml`, `llms.txt` and `blog.html`.

**The honesty trade named above was taken, and it dissolved on contact with the
research.** The plan expected to have to admit "we do not do Studio" somewhere
awkward. What the sources actually show is that the query has no single answer
at all, for anybody:

| System | Can a student download it? |
|---|---|
| Canvas Studio | Off by default per embed; a licensed add-on for the Studio-side download |
| Panopto | Off by default; enabled per folder, subfolder or recording |
| Kaltura / My Media | Depends which **player** the channel uses; the default has no download button |
| A plain file in the Files tab | Yes, like any other file |
| YouTube / Vimeo / Zoom link | Governed by that service, never by Canvas |

So the page's premise is **"there is no such thing as a Canvas lecture video"**,
and the honest scope statement stops being a confession and becomes the
article's whole structure. Every competing page answers for ONE of the five and
never says which - which is also why the answers people find contradict each
other.

**Where the limit went.** Per the Phase 0b rule, the body carries a section
headed *What this app covers* stating plainly that the app handles Panopto and
does not download Studio or Kaltura. The CTA box carries none of that; it names
**Panopto** in its heading and its first sentence, so the scope is disclosed by
the box's own strongest noun rather than by a disclaimer that argues against the
button.

**The best fact on the page is one nobody publishes: the transcript is a
SEPARATE permission from the video**, in both Studio and Panopto, and lecturers
who restrict the recording routinely leave captions open because turning
accessibility off is a decision nobody wants to defend. That is a legitimate,
actionable route, it is the better artefact for revision anyway, and it is the
natural bridge to the NotebookLM page.

**Five citations, all fetched 200 on 2026-08-27**, and two of them are the kind
of primary source this genre never has:

- Instructure KB 664517 - *"the download option is turned off by default for
  media you own, but you can enable the download option"*, plus the separate
  *Allow media download* and *Allow transcript download* toggles.
- Instructure KB 660507 - the Studio-side download is *"a legacy add-on that is
  now available with Canvas Plus and Canvas Next"*, so it is a **licence**
  question, not only a permission one. Nobody says this.
- Instructure Community 618390 - *"Studio videos are downloaded easily from your
  Studio account. But this is one at a time"*, and the path to media recorded
  through Canvas's own recorder: Account, Files, My Files, **Uploaded Media**.
- Panopto support, Enable Podcast Downloads.
- University of Michigan MiVideo KB 10274 - *"The default Media Gallery player
  does not have the download button enabled"*.

**Linking**: five contextual inbound links (homepage pillar 6, and all four of
the other articles that touch video), and it links out to four of them.

**One defect found in the browser, pre-existing on all five older articles.**
`.art a { color: var(--cyan) }` reaches into the CTA box, where both buttons are
anchors - so the **Download** button rendered cyan-on-blue at a **2.31:1**
contrast ratio while the byte-identical nav button was white-on-blue at
**4.95:1**. Below the 4.5:1 AA floor and below even the 3:1 large-text floor, on
the single element the box exists for, on every article, since the CTA boxes
were built. Fixed in the generator by restating the shell's own values; measured
after: **4.95:1**, in-article links still cyan, citations still muted.

**It is the same family as the Phase 1 trap, inverted** - there a broad
`a { color: inherit }` swallowed new links; here a broad `.art a` swallowed a
button's colour. **A broad link rule and a button that is an anchor is a
standing hazard on this site.** Neither was visible in review and neither failed
a test; both took a computed-style read in a real browser.

**Article 1 carried an honesty problem - RESOLVED 2026-08-27, see the write-up above.** The trade turned out not to exist: the research showed no system on that query has an unconditional answer, so naming the scope became the article's structure rather than a confession. The original note is kept below because the reasoning is still the right reasoning to apply to the next one.

**Article 1 carries an honesty problem that is the operator's call, not mine.**
The app downloads Panopto and does **not** download Canvas Studio - the engine
reports Studio as an undownloadable media stream (`core/canvas_logic.py:4686`).
An article that ranks for the video query must say so plainly, and will
therefore convert worse than its traffic suggests. My recommendation is to write
it anyway and be explicit, because it is the largest door into the site and the
rest of the course is still ours to fetch - but it is a real trade and it should
be made deliberately rather than discovered later.


#### Article 6, shipped 2026-08-27 - Phase 2 complete

`docs/back-up-canvas-course-before-losing-access.html`, 2,684 words, 5
citations.

**The research turned up a better article than the plan asked for.** The plan
wanted the `backup / archive canvas course` cluster. What the sources actually
show is that the premise most students hold is wrong, and in a way that costs
them the most valuable material.

**The deadline is a staircase, and the doors close in the worst possible
order.** Three of them, belonging to three different systems:

1. **Lecture recordings**, usually first. Stanford tells staff that viewers
   *"will no longer have access to video recordings under the Panopto Course
   Videos tool, typically the Sunday after grades are due"* - at a university
   that gives graduating students **120 days** of Canvas. Days against months,
   one institution, two halves of the same course. Harvard is blunter: *"for
   courses that are concluded, students will no longer see any Panopto videos,
   whether they are in an archived state or active"*, plus a January/June sweep
   that archives recordings over two years old and deletes archived ones over
   four.
2. **The course concludes** - read-only, and see below.
3. **Enrolment or account ends.**

So the largest files, the slowest to download, and the only ones nobody else
has a copy of, are the ones on the shortest clock. The article's priority list
is therefore recordings first and **files last**, which is the reverse of what
every other guide does, files being the obvious button.

**The headline finding, and it came free from article 3's research: Canvas's
own offline export refuses to run once a course is concluded.** The official
backup tool has a shorter life than the thing it backs up, and it dies at
exactly the moment somebody notices they need it. It is also an administrator
setting, and enabled per course on top of that, so there are three separate
ways for it not to be there. The article tells the reader to go and check for
the button today, which takes five seconds and is the only way to find out
before it matters.

**Two sections nobody else writes.** "How to check the backup is complete" -
play a recording from the *last* minute, because a truncated video looks
healthy until you try it; click into a discussion in the offline export,
because replies are usually left online-only; sort by size and look for
zero-byte files. And "if you have already lost access", which is honest about
what a polite email to a course coordinator recovers, and about the fact that a
data request reaches your submissions and grades but not the lecture slides.

**It gives the graduation article the hand-off the plan wanted.** That page was
dispositioned "keep, stop expecting traffic" because its SERP is 10/10
institutional. It now links here for the actionable half, which is the intent
it could never rank for itself.

**Measured: the cleanest page on the site.** 20% short sentences, **1% long**
(lowest of the eleven), 0.0 dashes per 1k, zero negation constructions, zero
rhetorical questions, zero anaphora runs, no banned lexicon.

**Not cited on purpose:** Oxford's Replay retention page (13 months to archive,
24 to deletion). Its URL 301s to a generic redirects page, so it has genuinely
moved. A dead citation is worse than one fewer. The Harvard and Stanford pages
403 to `curl` but that is WAF bot-blocking rather than a dead link - both were
confirmed by two independent searches with consistent extraction.

**Harness limitation, recorded so nobody repeats the hour I spent on it:
Playwright screenshots of this site come back blank.** A `.cta-row a.btn-nav`
with a measured `background-color: rgb(59, 113, 184)` screenshots as near-black,
and the element dimensions are correct, so it is the capture and not the page.
There is no `.reveal` on the article pages at all, so the animation is not the
cause. **Verify these pages by reading computed styles and geometry instead** -
for contrast ratios, overflow and anchor resolution that is stronger evidence
than an image anyway. Constrain `.art` to 350px in JS to test phone width;
`browser_resize` does not reflow the layout viewport.

### Phase 3 - build something that can be linked to

None of the above earns a link. These do. Both are bets, and the sizes below are
honest.

**3a. Original measured data: what Canvas's own export misses.**

This is the strongest idea in this document. Every `.edu` help desk, every forum
answer and every competitor page asserts that "Download as Zip can miss files
attached to modules", and **not one of them has ever put a number on it.** We
can, from the app's own audit runs against real courses, and those numbers are
already in `CLAUDE.md` and the audit registers.

- It is first-hand experience of exactly the kind Google's guidance names.
- It is a statistic, the #2 GEO method by measured effect.
- It is the single citable number an entire genre of pages needs and none has.
  That is what a link *is*: somebody needing a number they cannot produce.
- It costs no new research, only a careful, honest write-up of measurements that
  already exist, with the sample size and the method stated.

**State the method and the sample honestly, including how small it is.** A
number from a handful of real courses, described as such, is citable. A number
implied to be a survey is not, and this project's own rules would not survive
publishing one.

**3b. A crawlable directory of Canvas institution URLs.**

`shared/institutions.py` holds **4,757 institutions**, each with a Canvas
hostname that was *verified live* against `/api/v1/users/self` at generation
time. Cluster F shows the demand exists (`find my canvas url`, `canvas url
search tool`).

**Check the claim before building, because I checked it and it is weaker than it
first looks.** Instructure already operates *Find My Canvas URL* and a school
search on `instructure.com/canvas/login`. We will not outrank Instructure for
that query and should not try. What they do **not** appear to have is a
*crawlable* list - their search is client-rendered, so the hostnames are not
visible text. The opportunity is therefore long-tail and citation, not the head
term.

**Ship it as ONE searchable page, not 4,757 pages.** Google's spam policy defines
scaled content abuse as *"many pages generated for the primary purpose of
manipulating search rankings and not helping users"*. One page holding a
filterable, verified, country-grouped list is a tool. Four thousand pages each
holding a name and a URL is the thing that policy is about. **Do not generate
per-institution pages**, and if that is ever revisited it needs a real reason,
per page, to exist.

**Verify demand before spending the time**: search two or three specific
institution names plus "canvas url" and see whether anything ranks. If the
university's own page always wins, the directory's value is as a linkable
utility and an app-credibility surface rather than as traffic. That is still
worth having; it is a smaller prize and should be sized as one.

---


#### 3a SHIPPED 2026-08-27 - and the result inverts the premise

`docs/what-canvas-download-as-zip-misses.html`, 2,455 words, 4 citations.
Method published as `scripts/measure_export_gap.py`, which prints every figure
on the page including the per-course table.

**The data already existed and nobody had looked at it.** The live audit
harness writes a per-course Canvas census to
`_audit_runs/*/evidence/canvas/course_<id>.json`, carrying `files_tab`,
`module_file_ids`, `only_in_modules`, `files_tab_restricted` and the non-file
counts. 242 census files, **33 distinct courses**.

**The measured result, and it is the opposite of what the plan assumed:**

| | |
|---|---|
| Courses censused | 33, of which **22 hold no material** (programme shells) |
| Courses with files | 11 |
| **Files tab REFUSED outright** | **3 of 11**, holding **246 files** |
| Files tab present but incomplete | **1 of 8**, **3 files of 358 (0.8%)** |
| Non-file items across all 33 | **173** (84 announcements, 32 quizzes, 20 discussions, 20 assignments, 17 Pages) |

The failure every help desk warns about - a zip missing files attached to
modules - is the **rare** one. The common one is that Download as Zip cannot be
used at all, because an instructor disabled Files in course navigation. That is
a genuinely novel, counterintuitive, citable finding and it is the article.

**The 403 is verified as per-course rather than per-account**, which is what
makes it stand up: the same credential succeeded on 29 of the same 33 courses
in the same minutes. Stated in the article, because a reader should not have to
take it on trust.

**Publishing the deflating half is the point.** The 0.8% figure undercuts the
case for the software this site sells, and the article says so in those words.
A measurement that only ever flatters the measurer is marketing.

**It audited the site's own pillar page.** Article 1 said of module-attached
files *"This is the big one"* and gave the switched-off Files tab a shorter,
calmer bullet. The census says that ordering is backwards. Article 1 has been
corrected and now links to the measurement. **Third time this session that
writing one page has found an error in an earlier one** (article 5 caught
article 4; article 6 inherited article 3's finding; this one corrects article
1). Writing a page that has to be defensible is a better audit of the others
than re-reading them.

**Instructure documents the limitation nowhere.** A search of their own KB and
community for the behaviour returns the modules guide, the file-download guide
and threads of people asking, with no vendor statement either way. The article
says so, because it is part of why the claim went unchecked for so long.

**Honesty machinery, stated in the article rather than buried:** the sample is
33 courses from one student's enrolment at ONE university. The article tells
readers to quote it as "in 33 courses at one university" or not at all, gives
the two API calls so anyone can reproduce it for their own institution, and
asks to hear about contradicting results. **The institution is deliberately not
named** - it would add little to citability and would publish where the
operator studies, which is their call and not the writer's.

**Measured writing:** 23% short sentences, 4% long, 0.6 dashes per 1k, zero
negation constructions, zero anaphora runs, zero rhetorical questions.

**Two more defects in the AI-tell checker, found by running it on this page.**
It counted `<table>` cells as prose, which manufactured a phantom "rhetorical
question" out of the header cell `In a Files zip?`; tables are now stripped.
And `harness` was in the banned-lexicon list as a bare token, so the literal
noun ("audit harness") flagged five times - narrowed to `harness the` /
`harnessing`. **A first version of the table fix carried a comment claiming the
change moved the comparison article from 26% short to 18%. That was a
prediction written as a measurement, and it was false**: `sentences()` reads
`paragraphs()`, which extracts `<p>` only, so table cells never reached the
sentence statistics at all. Corrected in the file. Writing a number you have
not taken is the exact failure this article exists to argue against.

#### 3b - demand CHECKED 2026-08-27, verdict: build it, but size it as a utility

The plan said to verify demand before spending the time. Done, and it confirms
the plan's own suspicion rather than overturning it.

- **Head term**: Instructure owns it outright. `find my canvas url` returns
  their own *Find My Canvas URL* tool, their `instructure.com/canvas/login`
  school search, and their KB article *"Where do I find my institution's URL"*.
  Not contestable and the plan already said not to try.
- **Institution-specific**: the university's own page wins. `Erhvervsakademi
  Aarhus canvas url` returns `studerende.eaaa.dk`, and the answer
  (`canvas.eaaa.dk`) is surfaced directly in the results.

So by the plan's own decision rule the directory's value is **as a linkable
utility and an app-credibility surface, not as traffic**. Worth building
because the data already exists and is verified, and because the one thing
Instructure does *not* offer is a **crawlable** list - their search is
client-rendered, so no hostname is visible text.

**That makes server-rendered rows the entire point of the build.** A page that
injects its rows with JavaScript would reproduce the competitor's weakness and
have no reason to exist. It also has to satisfy the site's own no-JS rule.

**SHIPPED 2026-08-27** as `docs/canvas-url-directory.html`, generated by
`scripts/build_institution_directory.py` from `shared/institutions.py`.
**4,757 institutions, 957 KB raw / 93 KB gzipped.**

**Server-rendered rows are the build**, not a detail of it. Every hostname is
visible text in the HTML. The search box is created BY the script and inserted
at runtime, so with JavaScript off a visitor gets the whole list rather than a
control that silently does nothing. A refactor that moved row rendering into
JavaScript would look fine in a browser, pass every link test, and destroy the
page's only advantage over Instructure's own search.

**Not in the nav.** The nav is reserved for how to set up, how it works,
download and GitHub, and nothing else goes there (standing instruction). It is
reached from the token article's FAQ, the sitemap and `llms.txt`. Not in
`blog.html` either: it is a tool, not an article.

**Not grouped by country**, decided on the data: only 1,558 of 4,757 rows have
a known country, so country sections would file 3,199 institutions under
"unknown" and read as broken. Alphabetical, country as a chip where known, with
a note saying a blank one means unknown rather than anything about the school.

**It keeps the picker's honesty rule**: the list is not exhaustive, a missing
school is not an unsupported one, and Instructure's own school search is named
and linked as the authoritative source. We do not own this query and the page
says so.

**Three defects found by looking at it in a browser, all of them number
formatting, all invisible in the source.** The count label flipped from the
server-rendered `4,757` to `4.757` the moment the script ran, because a bare
`toLocaleString()` follows the BROWSER's locale and this machine is Danish.
Pinned to `en-US`. The `<title>`, the meta description and the search
placeholder all printed a bare `4757` beside it. **A page that renders one
number three ways is the kind of thing only a screenshot catches.**

`data-k` was dropped after measuring: it duplicated the name and host already
in the cells and cost **281 KB of the original 1.24 MB**. The filter builds its
key from `row.textContent` instead, which is the same string for free.

**Verified in the browser end to end**: 4,757 rows present, search box injected,
sticky header, no horizontal overflow, `harvard` filters to 5 rows including
`canvas.harvard.edu`, `copenhagen` to exactly CBS and Absalon with the local
name intact, a no-match query shows the empty-state message, and clearing
restores 4,757.

**One unrelated guard needed widening.** `test_no_stale_repo_urls` failed on
`marketing/SEO_FINDINGS_2026-08-27.md`, whose before/after table quotes the old
pre-transfer GitHub Pages URLs **as the defect it reports**. The guard was firing on
the write-up of the fix it exists to enforce. Exempted by a PROPERTY rather
than a filename: the line must carry an explicit dead HTTP status (404/410/301/
308) beside the URL, which is something only a report writes. A first draft
keyed on words like "old" and "redirect" and would have exempted any real link
in a sentence containing them. Positive control run: a real link is still
caught, prose containing "old" is still caught, only the documented-dead line
is exempt.


---

## 6. Per-article dispositions

| Article | Disposition |
|---|---|
| `how-to-download-all-canvas-files` | **Keep as the pillar.** Add citations, the statistics from 3a, the short-answer block. Make it the hub every other article links up to |
| `canvas-files-into-notebooklm` | **Keep and push hardest.** Best SERP odds of the five, and a competitor is out-positioning us on it. Add citations to Google's NotebookLM documentation. Watch `jasp-nerd` |
| `download-panopto-lecture-recordings` | **Keep, and split.** The permission framing cannot beat nine institutional pages. The transcript half is uncontested and is ours alone - promote it to article 2 |
| `save-canvas-assignment-feedback` | **Keep, retitle.** Retarget onto the phrasings people actually type: *download assignment with annotations*, *with comments*. The content is right and the title matches nothing |
| `canvas-access-after-graduation` | **Keep, stop expecting traffic.** Ten of ten institutional. Its job is internal linking and reassurance for a visitor who is already here. Let article 6 (*back up a course before you lose access*) carry the search intent instead |

---

## 7. What not to do

- **Do not scrap and rebuild.** Section 1.
- **Do not add articles before Phase 0 and 1.** More pages behind the same
  linking wall, carrying the same missing signals, multiplies a known defect.
- **Do not chase `canvas access after graduation` or the Panopto permission
  question.** Universities own them permanently. Complement, do not compete -
  which is already `STRATEGY.md` section 4, and it was right.
- **Do not generate per-institution pages.** Section 3b.
- **Do not keyword-stuff.** It is the one method measured to make things
  *worse*.
- **Do not buy links or run guest-post campaigns.** Generic 2026 link-building
  advice returns exactly that, and it is wrong for a free open-source student
  tool: this audience is on Reddit and in the Instructure Community, and the
  honest channel is answering questions well and disclosing authorship, which
  `PLAYBOOK.md` already lays out.
- **Do not add an `aggregateRating`, a fabricated survey, or any number that was
  not measured.** Settled in `STRATEGY.md`, and 3a lives or dies on it.

---

## 8. How to tell whether this worked

No analytics, by decision, so Search Console is the instrument.

- **Leading, weeks 1 to 4:** are the five articles *indexed*? As of the last read
  in `FINDINGS.md`, not one search-facing page was. Phase 1 is aimed directly at
  that, and indexing is the only thing worth watching until it happens.
- **Weeks 4 to 12:** impressions per article, and which queries. The prediction
  this plan makes, and can be judged on: **the NotebookLM and Cluster D pages
  will earn impressions before the graduation and Panopto-permission pages do.**
  If the reverse happens, the SERP reading in section 2 is wrong and the topic
  plan should be reopened.
- **Standing:** referring domains. Today that is effectively zero. If Phase 3a
  ships and it is still zero after three months, the linkable-asset thesis is
  wrong for this niche and the answer is entirely `PLAYBOOK.md`.
- **Do not measure with scripted `site:` queries.** `FINDINGS.md` records why
  they are not evidence: Bing and DuckDuckGo block scripted access, and a
  control query returned zero through the same parser.

---

## 9. Provenance

Everything in sections 2 and 4 was measured on 2026-08-26 and is re-measurable:
article metrics by parsing `docs/*.html`; link positions by byte offset in
`docs/index.html`; competitor traction from the GitHub API; SERP composition
from live search; the demand map from Google's autocomplete endpoint. Section 3
is external research, with the GEO figures from the Princeton / IIT Delhi study
and the FAQ deprecation dates from Google's own documentation notice.

The SERP and autocomplete data were collected from a Norwegian IP with US
targeting requested, and geo leakage was observed. Re-run from the target market
before treating any ordering as exact.

---

## 10. Keeping the prose from reading as machine-written

Added 2026-08-27, after the product owner predicted that article quality would
drift as the session got longer. **It already had, and it was measurable.**

`scratchpad/ai_tells.py` scores every built article against the countable tells
from tropes.fyi, Pangram's pattern guide, Forbes (Feb 2026) and Grammarly's
AI-word list. Only things that can actually be counted are in it: "sounds
robotic" is not a metric, sentence-length variance is.

**What the first run showed.** The five original articles and the three written
this session, on two axes:

| | original five | articles 1-3 |
|---|---|---|
| ` - ` used as an em dash, per 1k words | 2.0 to 5.7 | 5.5 to **9.1** |
| sentences of 35+ words | 3 to 6% | 15 to **19%** |

And the two co-occurred. **11 of 16 long sentences in the lecture-video article
were a 45-75 word clause held together by a PAIR of dashes carrying a
parenthetical** - the documented Claude signature almost exactly. The worst was
62 words with two dashes, a colon and a six-item list in one breath.

**This repo's no-em-dash rule does not catch it.** The rule bans the glyph. The
tell is the RHYTHM, and ` - ` reproduces it perfectly.

**After two rewrite passes** (splitting the sandwiches, dropping one dash of
each pair, trimming six- and thirteen-item lists back to what a person writes):

| article | dash/1k | 35+ word sentences |
|---|---|---|
| lecture videos | 9.1 -> **3.0** | 16% -> **5%** |
| transcript | 5.5 -> 4.2 | 15% -> 10% |
| quizzes/Pages | 7.3 -> 3.9 | 19% -> 12% |
| **access token** (written to target) | **0.0** | **6%** |

**Article 4 was written against the measured targets rather than edited into
them afterwards**, and it is the cleanest page on the site: zero dash
parentheticals in 2,425 words, the highest short-sentence share (19%), the
highest contraction rate, and no banned lexicon.

**Rules that came out of it, for whoever writes article 5:**

1. **Do not rewrite every long sentence into a short one.** Uniform short
   sentences are the same tell wearing different clothes. The target is
   variance, and the original articles' 9-10 word standard deviation is the
   benchmark.
2. **A dash before a conjunction is the worst case.** ` - and `, ` - but `,
   ` - so `: a dash standing in for a full stop. Four of these were in one
   article.
3. **Cut enumerations to three.** A six-item list is an extended tricolon, and
   the reader stops reading at four.
4. **Run the scanner before shipping, not after.** It lives at
   `scripts/check_ai_writing_tells.py` and reads its article list from
   `PAGES`, so a new page is covered without anyone extending it. It is
   deliberately NOT a test: these are judgement calls about prose, and a
   hard threshold on sentence length would fail a build over a paragraph
   somebody wrote well. Run it, read the numbers against the table above,
   and decide.

**A metric that always fires is a guard that cannot say no.** The first version
of the scanner counted 4 to 8 "rhetorical questions" on every page and I nearly
acted on it. Seven of eight were **FAQ headings**, which are questions by
design. The scanner now excludes the FAQ, and the real count is 0 to 1 per page.
Same lesson this repo already records for blind audit oracles: check what your
own diagnostic is measuring before believing its number.

**Known scanner limitation**: `banned` substring-matches, so "a module that
unlocks later" registers as the marketing word "unlock". One standing false
positive, left in rather than special-cased, because narrowing a guard to
silence a known-good hit is how it stops catching the real one.
