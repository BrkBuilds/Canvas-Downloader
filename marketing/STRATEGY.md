# Strategy: who this is for, what we say, and what is already decided

Read this before writing a word of copy, choosing a keyword, or proposing a
rename. The decisions at the bottom are **settled**; reopening one costs the
next person the same argument twice.

---

## 1. Who the user is

A university student who uses Canvas for coursework, in an English-speaking
country, and **not predominantly American**. Measured from the Microsoft Store
dashboard on 2026-08-20, by installs: Philippines 82, United States 79,
Australia 70, South Africa 62, India 55, Nigeria 27, United Kingdom 24, across
15 pages of countries.

**This corrects an earlier reading, and the correction matters.** This section
used to say "most likely in the United States", measured from the app's own
institution directory (1,330 US institutions against 9 Danish). That directory
measures where Canvas *tenants* are, not where *users* are. The US is about 10%
of installs. Copy or examples that assume an American student are speaking to
one visitor in ten. English first is untouched and if anything stronger, since
every country on that list is English-speaking. Full table and the engineering
consequence in [FINDINGS.md](FINDINGS.md).

They are not a system administrator, not an instructor, and not a developer.
They arrive at one of four moments:

1. **"I need everything before I lose access"** - graduating, or a course is
   about to conclude. Highest intent, seasonal, and emotionally loaded.
2. **"Downloading these files one at a time is absurd"** - mid-semester
   frustration. This is the biggest group.
3. **"I want my course in an AI tool"** - NotebookLM, ChatGPT, Claude. Newest,
   fastest-growing, least contested.
4. **"I want the lecture recordings"** - Panopto. Distinct and high volume.

## 2. THE VOCABULARY RULE

**Students say "Canvas". They do not say "LMS".**

This is a direct instruction from the product owner (2026-08-19) and it
overrides SEO instinct. "LMS" is administrator vocabulary; to the person this
product is for it reads as noise, or as a sign that the page was not written for
them.

- **Visible copy: "Canvas".** Page text, headings, meta descriptions, button
  labels, Store listing, installer strings, release notes.
- **"Canvas LMS" is permitted in exactly one place: machine-readable schema**
  (`applicationSubCategory`, JSON-LD keywords) and the `llms.txt` disambiguation
  line, where it separates this product from Spotify Canvas and the HTML canvas
  element for a *machine*, and no student ever reads it.
- The footer's existing "Not affiliated with Instructure or Canvas LMS" is a
  legal-style disclaimer and stays as it is.

Related standing rule for all prose in this repository: **no em dashes**. Use
" - ". When quoting the app's own copy, quote it character-exact rather than
reflowing it.

## 3. Positioning

**What it is:** the thing that does what Canvas will not do.

Canvas can zip one course's Files tab at a time. It cannot do multiple courses,
it frequently misses files attached directly to modules, and it has no bulk
export at all for Pages, assignment briefs, announcements, discussions, quizzes
or the feedback you were given. That gap *is* the product, and stating the gap
plainly is more persuasive than any feature list.

**What no competitor combines. CORRECTED 2026-08-27** - two of the three
things this list used to claim have been matched, and pitching on them now is
pitching on something a reader can disprove in one click.

1. **Lecture recordings.** Panopto sits outside Canvas, so a browser extension
   structurally cannot reach it - jasp-nerd's says so in its own README. No
   script does it either.
2. **Conversion as it downloads**, and **local transcription**.
3. **It keeps files you have edited.** On a re-sync an annotated file survives
   and the new version lands beside it. Nothing else on the market does this,
   and nothing else advertises it, which is a gap worth owning.
4. **Quiz questions**, not just quiz titles.

**What is no longer a differentiator, and must not be claimed as one:** "every
course in one run" and "it remembers between runs". A free browser extension
does both (see below). "The categories Canvas has no export for" is now a
partial claim rather than a whole one: extensions get Pages, assignments,
announcements and discussions too. Quizzes and feedback are still ours.

**Trust is a feature and must lead, not trail.** The product asks for an access
token and ships unsigned, so it triggers SmartScreen and Gatekeeper warnings.
Every surface therefore says, early and without being asked: runs on your own
computer, no account, no server, nothing uploaded, every line of code public,
reads only what your own Canvas account can already open.

**Be honest about the limits, everywhere.** The pages state that some
institutions disable access tokens, that Office conversions need the Office
desktop app, and that Intel Macs are unsupported. A page that only sells does
not earn the link that makes it rank, and the audience is students who have been
burned by "free" tools.

## 4. Search strategy

**The `.edu` help desks own the money query and cannot be outranked.** Stanford,
Illinois, Clemson, Pitt, NCTC and UNT all rank for "how to download all files
from Canvas at once", on domains a months-old site cannot compete with.

**They can be complemented instead.** Every one of them stops at the same wall,
and that wall is the pitch. So the content strategy is to be the page that
starts where they stop: what Canvas can do by itself, honestly and completely,
then what is left over and how to get it.

**Long tail first, brand term later.** The brand phrase is contested (see the
settled decision below). Winnable phrases now are the specific ones: "download
all files from canvas", "canvas bulk download app", "canvas access after
graduation", "download panopto lecture", "canvas files notebooklm".

**How many pages there should be is decided by demand, not by a cap.** Add a
page when there is a distinct question with measured demand behind it, and do
not add one otherwise. An earlier version of this section carried a fixed
"two strong pages beat eight thin ones" rule; it was a scope answer given in
one session and had no evidence behind it, so it is gone rather than
restated. See [BLOG_PLAN.md](BLOG_PLAN.md) for the demand map.

## 5. The competitive picture

Re-verified **2026-08-27** against each project's own documentation, which
moved several rows. The 2026-08-20 version of this table was written from search
results rather than from reading the repositories, and it understated the
competition materially.

| Competitor | Where it beats us | Where we beat it |
|---|---|---|
| Canvas's own Download as Zip | Nothing to install, no token | One course at a time; misses module-attached files; no Pages, assignments, announcements, quizzes or feedback |
| **jasp-nerd/canvas-course-downloader** (extension, 38 stars) | **No token at all** - rides your browser session; zero setup; multiple courses; incremental mode; files, Pages, assignments, announcements, discussions, syllabus, grades | No Panopto (states it outright); no conversion; no edit protection; Pages arrive as HTML summaries |
| Other Chrome extensions | Zero setup, no token | Narrower coverage; check the permission scope, not all are Canvas-only |
| **davekats/canvas-student-data-export** (script, 265 stars) | Far more established than us; assignments, submissions, announcements, discussions, Pages, files, modules, all courses | Needs Python 3.8+, a credentials file and a token; Node 16 for HTML snapshots; **cannot capture quiz data**; maintenance is the user's |
| Other scripts and CLI tools | Infinitely flexible; best option for a CS student | One popular repo last pushed **December 2023**; Canvas changed token rules twice since |
| `canvasdownloader.com` | Owns the .com, far higher search volume | Different product entirely: it downloads **Spotify** Canvas loops |

**The token gap is the one that is widening against us.** Canvas has been cutting
access-token lifetimes since September 2025, so "no token needed" gets more
valuable every deploy while our setup cost stays the same. Do not pitch against
it; pitch on what a browser cannot reach.

**Star counts, for honesty:** davekats 265, jasp-nerd 38, kas 14, jamubc 5,
**this project 2**. Stars are a poor proxy for a desktop app shipped through an
installer and the Microsoft Store, and that is worth saying - but not instead of
saying the number.

**Say all of this on the site, fairly.**
[`canvas-download-tools-compared.html`](../docs/canvas-download-tools-compared.html)
does, naming the competitors, quoting their documentation, and pointing three of
its five recommendations away from this app.

### The differentiation is by SHAPE, and the shape decides the audience

Settled 2026-08-27 by the product owner, and it is the frame every comparison
should use rather than a feature list.

The competing tools are, in effect, Canvas's own **Download as Zip** with more
reach, wrapped in a different package. That is a useful thing to be and the
comparison page says so. What it is not is the same product.

- **A browser extension is a button.** It exists while the popup is open and it
  is built to be that way. It cannot run on Thursday morning while you are
  asleep, cannot show you what changed and wait, and has nowhere to keep a
  record of a file you annotated.
- **A CLI tool is written by developers for developers.** Python, a
  dependency install, a credentials file, a terminal, and the maintenance is
  the user's. A legitimate audience, and not the one this product serves.
- **Canvas Downloader is a resident application** meant to accompany a student
  across a whole degree and many semesters. That is the positioning.

**The two USPs to lead with, in this order:**

1. **Sync mode.** Analyze, Review & Sync produces a full review of every
   difference between the folder and the course before anything is written -
   New Files, Updates Available, updates to files the student has edited,
   Deleted on Canvas, Deleted Locally. Quick Sync does the safe subset in one
   click. **Today's files** fetches the day's new material on its own and shows
   what arrived across every course in one list. Nothing else on the market has
   any of this, because none of the other shapes can hold state between runs.
2. **Conversion means the folder is drag-and-drop ready.** NotebookLM and
   Claude do not accept `.pptx`, `.doc`, or the HTML Canvas exports its Pages
   as. Converting on the way down is the difference between a folder and a
   usable folder, and it is what most students need right now. A browser
   extension structurally cannot do it: converting a PowerPoint needs software
   installed on the machine.

**On GitHub stars, and how to talk about them.** davekats has 265 and this
project has 2. Say the number - but say what it measures. A star is a developer
bookmarking a repository; nobody stars an app they installed from the Microsoft
Store. Against those 2 stars the app has **900+ installs**. The two numbers
count the two audiences the two shapes were built for, which is the whole point
rather than an excuse. What the competitors genuinely have is age and the trust
that comes with it, and that is worth conceding plainly.


---

## SETTLED DECISIONS

Do not re-litigate without new evidence. Each has its full reasoning in
[FINDINGS.md](FINDINGS.md).

### The brand-name question is postponed
Three responses were proposed and all rejected by the product owner on
2026-08-19, with two corrections that became the rules above: "Canvas LMS" is
not a usable disambiguator because the audience does not use the word, and the
Spotify collision does not need solving because a user searching for Canvas
*files* will filter it out and take the next result. Revisit only with Search
Console data.

### No analytics script
Search Console and Bing Webmaster only, decided 2026-08-19. The consequence is
accepted: the funnel below the click is invisible. If this changes,
`docs/privacy.html` changes in the same commit.

### English first, no localisation
Settled on the institution-count measurement above.

### Publish usage, never opinion, until there is an opinion to publish
Settled 2026-08-21. The Store has 0 ratings and 0 reviews after 750 installs, so
the site says "used by", carries no `aggregateRating` markup, and states no
claim about how anyone feels about the product. Enforced by
the two surfaces by hand (`docs/index.html`, `docs/llms.txt`). Revisit when the in-app rate prompt exists
and real reviews follow.

### Every published number is rounded down
Settled 2026-08-21. The site has no analytics and no build step, so nothing can
recompute a figure at render time. Rounding down is what keeps a hand-written
number true: the published figures are LIFETIME CUMULATIVE totals, so they can
only go up, and a rounded-down one can therefore only ever understate.

**No as-of date on a lifetime figure.** That was proposed, and removed by the
product owner: a date on a number that cannot become false is decoration. The
dating rule still applies to any WINDOWED figure ("in the last 6 months"), which
is what it was written for.

### Say what is true; do not narrate what is missing
Settled 2026-08-21. An early draft of `llms.txt` noted that the Store has no
reviews yet. Removed, because an assistant latches on to a fact like that and
builds a story from it, and the story it tends to build is that the product is
unvetted and should not be downloaded. Omission is both true and safer. There is
a test for this, because the instinct to disclose is strong.

### Do not add width and height to the site's images
Measured CLS is 0.0057 desktop and 0.0013 mobile against a 0.1 threshold. Two
hundred edits for no measurable gain.

### One folder, one configuration
Not a marketing decision but it constrains the copy: a downloaded course folder
keeps the file-type scope it was created with, and there is no UI to widen it.
Never write copy implying a folder's scope can be changed after the fact; the
honest instruction is to download the course again with All Files.

### The homepage does not teach the login
Settled 2026-08-26 by the product owner. The homepage carried the full
walkthrough - Canvas URL, access token, the video, ~370 lines - directly under the
download buttons. It explained a screen the visitor cannot reach yet, which is
friction placed in front of the one action that page exists for, and it removed
**24% of the page height** (3,925px on mobile, measured).

The walkthrough belongs in three places and only three: **`guide.html#api-token`**
(the long version, with the clip), **`win-setup.html`** and **`mac-setup.html`**
(the short version, three points each). It is short in all three - a setup page is
read by someone who has already committed, but they still did not come to read.

What stayed on the homepage is the half that answered a **security** question
rather than a setup one - the token's scope, as the fifth card in *Fair questions,
straight answers*. That is where a hesitant visitor looks, and it is a claim about
what the app can do, not an instruction to follow.

`tests/test_website_login_claims.py::test_the_homepage_does_not_teach_the_login`
keeps it out, matched on the Canvas controls a walkthrough must name.

### The primary nav holds four items, permanently
Settled 2026-08-26 by the product owner. The nav is **How to set up**, **How It
Works**, **Download** and the **GitHub / 100% Open Source** link. Nothing else
goes in it, ever - not the blog, not a directory, not a future landing page.

It is a decision about what the nav is FOR, so it does not reopen when a new
page wants distribution. Those four are the visitor's whole journey: learn what
it does, learn how to set it up, get it, and check it is real. A fifth item
competes with **Download**, which is the one action every page exists to
produce.

**The consequence has to be paid somewhere else, and it is real.** Article pages
therefore need contextual body links and in-page placement to be discoverable at
all; a footer link is not a substitute and never was. See
[BLOG_PLAN.md](BLOG_PLAN.md) Phase 1, which is written around this constraint
rather than against it.

---

## Rules for anyone writing copy here

1. **Answer the question first, then say what we built.** In forums this is the
   difference between a contribution and a removed post; on a page it is the
   difference between a link and a bounce.
2. **Disclose authorship every time** in any community.
3. **Never post the same text twice.** Copy-paste across threads is the clearest
   spam signal a moderator has.
4. **State limits in the same breath as claims.**
5. **Every number must be measured**, and the measurement conditions stated. The
   worst error in this folder's history was a confident performance verdict
   derived from the wrong profile.
