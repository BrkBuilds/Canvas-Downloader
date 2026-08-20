# Strategy: who this is for, what we say, and what is already decided

Read this before writing a word of copy, choosing a keyword, or proposing a
rename. The decisions at the bottom are **settled**; reopening one costs the
next person the same argument twice.

---

## 1. Who the user is

A university student who uses Canvas for coursework, most likely in the United
States. Measured, not assumed: the app's own verified institution directory
holds **1,330 institutions with a known country in the US against 9 in
Denmark**, plus 3,199 `.instructure.com` tenants that are predominantly US.

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

**The three things no competitor combines:**

1. Every course in one run, not one page or one course at a time.
2. The categories Canvas has no export for.
3. Sync, so it stays current instead of being a snapshot you keep repeating.

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

**Two strong pages beat eight thin ones.** Thin pages actively hurt. Add a page
only when there is a genuinely distinct question to answer well.

## 5. The competitive picture

Verified 2026-08-20.

| Competitor | Where it beats us | Where we beat it |
|---|---|---|
| Canvas's own Download as Zip | Nothing to install, no token | One course at a time; misses module-attached files; no Pages, assignments, announcements, quizzes or feedback |
| Chrome extensions (three share our name) | Zero setup, no token, fast for one messy module | Work per page not per account; no "all courses"; no memory between runs; broad permissions |
| Scripts and CLI tools (five GitHub repos share our name) | Infinitely flexible; best option for a CS student | Needs Python or Node and a terminal; maintenance falls on the user |
| `canvasdownloader.com` | Owns the .com, far higher search volume | Different product entirely: it downloads **Spotify** Canvas loops |

**Say all of this on the site, fairly.** The comparison page does, including the
cases where an extension or a script is the better answer.

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

### Do not add width and height to the site's images
Measured CLS is 0.0057 desktop and 0.0013 mobile against a 0.1 threshold. Two
hundred edits for no measurable gain.

### One folder, one configuration
Not a marketing decision but it constrains the copy: a downloaded course folder
keeps the file-type scope it was created with, and there is no UI to widen it.
Never write copy implying a folder's scope can be changed after the fact; the
honest instruction is to download the course again with All Files.

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
