# The Microsoft Store listing

**This is the source of truth for the Store listing copy.** Partner Center is a
form, not a repository: nothing there is versioned, diffable, or visible from
another machine. So the copy lives here and is *pasted* there, which makes the
next update a diff instead of a rewrite.

Read [STRATEGY.md](STRATEGY.md) before changing a word of it, and
[FINDINGS.md](FINDINGS.md) before "discovering" anything.

Written 2026-08-24 for the **v2.0.0 -> v2.0.2** submission.

### The working page

`marketing/store-listing.html` is a rendered version of this document with a
copy button and a live character count on every field. Open it beside Partner
Center. It is **generated** by `python marketing/build_store_page.py` from this
file, so the two cannot disagree - and because a generated file that is also
checked in ships whatever was last committed,
`tests/test_store_page_generated.py` re-renders it and fails if the committed
copy has gone stale. Never hand-edit it.

That test also asserts every limit below, so this document cannot quietly drift
over one. Seven positive controls were run against it (a hand-edited page, an
over-length short description, a keyword set over the word budget, a keyword
over 40 characters, a feature line with its own bullet, an em dash, and a URL in
the description) and all seven fail as they should.

---

## Why this surface matters more than the website

Measured, not assumed. The Store is **~94% of all installs** and it is the only
surface of this product that ranks; `PLAYBOOK.md` records an AI search assistant
summarising the product by quoting **the Store copy**, not the site. Improving
the listing is therefore the cheapest reach available.

---

## 1. WHAT WAS BROKEN, MEASURED 2026-08-24

### 1.1 The Privacy Policy link was a 404. So was the App website link.

| Field | Value on the live listing | Result |
|---|---|---|
| Privacy policy | `birkls.github.io/Canvas_LMS_batch_file_downloader/privacy.html` | **404** |
| App website | `birkls.github.io/Canvas_LMS_batch_file_downloader/` | **404** |
| Support | `github.com/birkls/Canvas_LMS_batch_file_downloader/issues` | 200 (redirects) |

**The mechanism, and it is the reusable part.** GitHub redirects a renamed
*repository* for ever, which is why the support link survives. It does **not**
redirect `<olduser>.github.io` after a **username** change, because the old user
page host stops existing. So the `birkls` -> `BrkBuilds` move silently broke the
two links that are pure Pages URLs and left the one that goes through
`github.com` working. That difference is exactly why a spot check of one link
would have concluded everything was fine.

Same root cause as the `og:image` 404 already in FINDINGS. **When an account is
renamed, every published `*.github.io` URL is dead - resolve them, do not reason
about them.**

Cost: every one of 800+ installers who clicked "Privacy policy" got a dead page,
on a product whose entire positioning is that trust must lead. It is also
policy-relevant - Store Policy 10.5.1 requires a working privacy policy.

### 1.2 The listing described a build that predates two headline features

The Store is on **v2.0.0** (`Notes` field: *"First release on the Microsoft
Store ... Canvas Downloader v2.0.0"*). **612 commits** separate it from v2.0.2.

Panopto lecture recordings and the Today page / daily auto-sync **both landed
between v2.0.0 and v2.0.1**. So their absence from the listing was never a copy
mistake - the shipped Store build genuinely does not have them. Check what the
shipped artifact contains before writing a gap up as a copy defect.

### 1.3 `Additional license terms` was empty, and it is the right home for the GPL offer

FINDINGS records the GPL-3 duty as *"put the source URL in the Microsoft Store
listing **description**"*. Microsoft's own listing guidance says, verbatim:

> Do not include HTML, code snippets, or URLs in the description field. Instead,
> provide support, privacy policy, and website links in their designated
> submission fields.

while the **Additional license terms** field says, also verbatim:

> If you enter a single URL into this field, it will be displayed to customers as
> a link that they can click to read your additional license terms.

So the field designed for licence terms explicitly accepts a URL and the
description explicitly does not. **Both are used** (section 3.7): the clickable
offer goes in the licence field, and the description carries a scheme-less
`github.com/...` mention so the source is findable without tripping the URL
guidance. That satisfies GPLv3 section 6(d) more strongly than the description
line alone, and removes a certification-rejection risk.

---

## 2. WHERE THE APP ACTUALLY RANKS IN STORE SEARCH

Measured 2026-08-24 against the live Store search API, US market, Windows.Desktop.
**This is the evidence the keywords are chosen from.**

| Query | Rank | Who owns the top spots |
|---|---|---|
| `canvas downloader` | **#1** | us |
| `canvas downloader sync` | **#1** | us |
| `canvas course` | **#8** | Canvas Connect, Coollage, Ink Canvas |
| `Credential Manager canvas` | #9 | (phrase appears only in our description) |
| `canvas` | not in top 8 | Canva, Corel Painter, Mental Canvas |
| `canvas lms` | not in top 20 | Canvas Connect, Camo Studio |
| `panopto` | **not in top 20** | screen recorders |
| `lecture downloader` | **not in top 20** | Lecture Countdown, Allen Digital |
| `notebooklm` | **not in top 20** | note-taking apps |
| `download course files` | not in top 20 | "Udemie : Course Downloader" |
| `download all files` | not in top 20 | Files App, Free Download Manager |
| `bulk download` / `batch download` | not in top 20 | download managers |
| `university student files` | not in top 20 | Power Planner |

**Three things follow, and each one changed a decision:**

1. **We rank for the brand name and essentially nothing else.** Title match
   dominates: exact title = #1, partial ("canvas course") = #8.
2. **The description IS indexed, but weakly.** `Credential Manager canvas`
   ranks #9 on a phrase that exists nowhere but our description, while
   `AI-ready conversion` and `syllabus announcements` - also description-only -
   return nothing. Description text alone will not win a term; keywords are the
   lever the Store provides for it.
3. **`panopto`, `lecture downloader` and `notebooklm` are UNCONTESTED**, in the
   sense that everything currently ranking for them does something else. Those
   are the cheapest wins on the board.

### The exclusion that matters more than the inclusions

Ranking now blends relevance with **download-through rate**: if people search a
term, see the app and do not install, the algorithm learns the app is not
relevant for that term. So generic download-manager phrases were **deliberately
left out** of the keyword set even though we are absent from them. Somebody
typing `bulk download` wants a download manager, would not install this, and
the failed impressions would actively cost us. `bulk course download` is kept
because the word *course* makes the intent ours.

### The Product Name question, raised and NOT acted on

Title match is by far the strongest ranking field, and several apps ranking
above us in adjacent queries are plainly exploiting it (*"Video Downloader 4K -
Bulk GetVid"*, *"Digital Notebook - Smart Pencil Notes & PDF editor"*). A
reserved name like `Canvas Downloader: Bulk Course & Lecture Saver` would put
keywords in that field.

**Not done, for a stated reason.** Microsoft's guidance is that the listing name
and the package name should match, and the package `DisplayName` is
`Canvas Downloader`; the app's own window, Start menu entry and website would
all keep the short name while the Store showed a longer one. That is brand
damage in exchange for a ranking bet. `STRATEGY.md` also postpones the brand-name
question generally. Revisit only with real Store search-term data.

---

## 3. THE COPY

Paste verbatim. Character counts are measured against the real limits, which are
quoted from Microsoft's current docs.

### 3.1 Product name  (unchanged)

```
Canvas Downloader
```

### 3.2 Short description  -  it IS a field, under Supplemental fields

**Corrected 2026-08-24 against the live submission.** This document previously
said the field does not exist in Partner Center's MSIX flow. It does. It is the
second-to-last control under **Supplemental fields**, a section that is
**collapsed by default** - which is why a scan of the page found no such field
and concluded it was absent. Microsoft's documentation was right and the reading
of the page was wrong. Same class as every other entry in this repository that
begins "measured, not read": a collapsed section is invisible to a look, so
expand every one of them before reporting a field missing.

Limits: 1,000 characters, of which roughly the first **270 are shown**. Partner
Center's own hint calls it "a shorter, catchy description that may be used in the
top of your product's Store listing".

**It is a SECOND slot, so it has to say a SECOND thing.** The obvious move is to
paste the description's opening line, which is what the live submission currently
holds - and a reader who sees both then meets one identical sentence twice, in
the two highest-value positions on the page. Use this instead. 223 characters,
and it carries lecture recordings, transcripts, NotebookLM, free/open-source and
privacy, none of which the opening line has room for:

```
Get all your Canvas course files onto your computer in one run, then keep them up to date automatically. Lecture recordings, transcripts and AI-ready files for NotebookLM included. Free, open source, nothing leaves your PC.
```

The same text is the right length for **directory listings** (AlternativeTo,
Softpedia, Product Hunt), so one string serves both surfaces.


### 3.3 Description  -  3,444 chars (limit 10,000)

**Written by the product owner, 2026-08-24, replacing a draft of mine. The
reasoning is a rule, not a preference, and it is recorded here so it is not
undone by the next person who reads `STRATEGY.md` and applies it too literally.**

> The first line of text is really the only thing people read, and is CRUCIAL in
> terms of conversion rate. Furthermore you started explaining the pain point,
> but no one needs to read their problem - they already know it, they need to
> know the solution and whether/how it solves their problem.

Both halves are right, and the second one corrects a genuine mistake of mine.
`STRATEGY.md` section 3 says that stating the gap Canvas leaves is more
persuasive than a feature list - and that is true **on the website**, where there
is room to build an argument and a visitor arriving from a search may not have
framed their own problem yet. A Store listing is the opposite situation: the
reader is already looking at a downloader, so a paragraph describing their
problem back to them spends the highest-value space on the page restating what
they came in knowing. **The website argues; the listing answers.** My draft
opened with a whole paragraph on what Canvas cannot do. That paragraph is gone.

Verified: **0 em dashes**, **pure ASCII** so nothing can mojibake in the form,
**no `http(s)://`** per Microsoft's own guidance, and "LMS" appears once, in the
legal disclaimer.

```
Canvas Downloader downloads all your Canvas course files to your computer and keeps your folders up to date - organized, offline, and ready to study.

DOWNLOAD EVERY COURSE AT ONCE
Tick the courses you want and the app pulls all of them. You can download EVERYTHING from Canvas: lecture slides, readings, module files, the syllabus, assignments, announcements, discussions, quizzes, and the feedback on your own assignments, including files that are only linked inside an assignment, announcement or discussion instead of uploaded to Files.

Folders come out organized the way your courses are, or all in one folder if you prefer. Use Custom Download mode for full control of what to download, or use Quick Download and its five ready-made presets to download Canvas courses quickly in just two clicks.

SYNC INSTEAD OF STARTING OVER
After downloading, use the intelligent Sync mode later to download only new or changed files. Quick Sync is one click. Sync Review compares your course folder to your Canvas course and shows you exactly what is different - all before anything is written - sorted into new files, updates, files you edited, files you deleted, and files your teacher removed. For students who want the full overview, perfect before exam season.

Canvas Downloader never overwrites a file you edited, never closes an Office document you have open, and it never deletes anything of yours - your files are safe.

AUTO-SYNC EVERY MORNING
Switch on daily sync and pick your courses. From then on, the first time you open the app each day, it quietly fetches everything new. The Today page shows exactly what arrived, grouped by course, with buttons to open the downloaded files straight from the app.

READY FOR NOTEBOOKLM AND OTHER AI TOOLS
Turn on AI optimization and the app converts files as it downloads them: PowerPoint and Excel to PDF, Canvas pages to plain text, archives unpacked, video to audio, and more. A fully AI-optimized course folder can be dragged straight into NotebookLM, and files will be optimized for use in ChatGPT, Claude or Gemini.

LECTURE RECORDINGS AND TRANSCRIPTS
Courses that post lectures through Panopto can be saved straight into your course folder as video (MP4), audio (MP3), a plain-text transcript, subtitles (SRT), or a shortcut back to the original recording. Transcription runs on your own computer, so nothing is uploaded and it costs nothing.

FIND YOUR UNIVERSITY
A searchable directory of 4,750+ verified Canvas schools sits on the login screen. Pick yours and the address fills itself in. If your school is not listed, type the address as normal and everything works exactly the same.

PRIVATE BY DESIGN
No account. No server. No analytics. No telemetry. Nothing is uploaded anywhere, ever. You sign in with an access token you create yourself in your own Canvas settings, which is stored safely in Windows Credential Manager, and it is only ever used to talk directly to your own university's Canvas. The app reads only what your own Canvas account can already open.

FREE AND OPEN SOURCE
Built by a student, for students, given away to all. Used by students in 100 countries. Canvas Downloader is free software licensed under the GNU General Public License v3 or later, and the complete source code is public at github.com/BrkBuilds/Canvas-Downloader

Canvas Downloader is an independent project and is not affiliated with, endorsed by, or connected to Instructure, Inc. or Canvas LMS.
```

#### Four edits made to the owner's text, and why

**1. "hidden behind links in your canvas pages" became "only linked inside an
assignment, announcement or discussion instead of uploaded to Files".** The
capability is real and it is one of the strongest sentences in the listing, but
it named the wrong place. `core/canvas_logic._extract_canvas_file_links` parses
an HTML body for `<a href>` containing `/files/`, resolves the id and downloads
it - across **14 call sites**, all of them assignment descriptions, announcement
and discussion messages, and quiz descriptions. A Canvas **Page** body
(`page_obj.body`) goes straight to the saver with no link extraction, so the
strict reading of "canvas pages" was false. Naming the real places is also more
concrete, which is worth more than the vaguer phrasing.

Note the deliberate narrowness: it reads `<a href>` and **nothing else**. A bare
`/files/<id>` sweep would also match the `<img src>` and the `data-api-endpoint`
beside it, and a banner image in a discussion is not a file the student is
missing. `tests/test_audit_inline_scope.py` pins that contract, after an
over-strict audit oracle invented a HIGH finding from exactly this.

**2. "never touches documents you have open" became "never closes an Office
document you have open".** The narrower claim is exactly what v2.0.2 fixed and is
unambiguously true: apps the user already had open are never quit, and an
undescribable document is never treated as ours. The broader claim was not
strictly guaranteed, because a conversion CONSUMES its source, so a `.pptx` that
happens to be open can be replaced by its PDF. That is opt-in and shown on the AI
conversions card, but it is not "never touches".

**3 and 4. Capitalisation.** "from canvas:" became "from Canvas:", and "A fully
ai optimized" became "A fully AI-optimized". Canvas is a proper noun and the
product being named; the same class of slip as the three in the carousel images.

#### Two things left exactly as the owner wrote them

Flagged, not changed - they are judgment calls rather than errors:

- **Word is absent from the conversions list** ("PowerPoint and Excel to PDF").
  The app does convert legacy Word (`.doc`, `.rtf`, `.odt`) to PDF, and the
  Product Features list in 3.5 still says "PowerPoint, Word and Excel". The
  description is not false because it ends with "and more", but the two surfaces
  now disagree.
- **"For students who want the full overview, perfect before exam season."** is
  a sentence fragment.


### 3.4 What's new in this version  -  1,313 chars (limit 1,500)

Written for someone upgrading from **v2.0.0**, which is the only version any
Store user has. It therefore covers v2.0.1 as well.

```
This is a big jump from the version on the Store. Two major features arrived since, plus a long list of fixes.

Lecture recordings. Courses that use Panopto can now be saved into your course folder as video, audio, a plain-text transcript, subtitles, or a shortcut back to the recording. Transcription runs on your own computer.

Daily auto-sync. The new Today page fetches everything new from your chosen courses the first time you open the app each day, and shows you exactly what arrived.

Find your university. A searchable directory of 4,750+ verified Canvas schools now sits on the login screen, so you do not have to know your Canvas address.

Name your own courses, and see those names everywhere, including in your sync history.

Four times faster. Pages open in a measured 487 ms instead of 2046 ms, and transitions no longer flicker.

Your files are safer. Fixed: a file Canvas listed could be missing from the review screen entirely; re-downloading a course could remove the protection on a file you had edited; a converted file could be re-offered as deleted for ever; a half-written PDF could replace your only copy of a document; Office could be closed with your unsaved document still in it.

Now licensed under GPL-3.0-or-later. Still free, still open source, still does everything it did before.
```

### 3.5 Product features  -  12 items (max 20, max 200 chars each)

**Replaces all 9 current ones.** The old set had two items saying the same thing
("Convert all your course files to AI-ready file formats automatically" and
"100% AI-ready study files") and several written as marketing sentences. The
category leader on this Store (Power Planner, 4.8 stars, 2,760 ratings) uses
eight terse functional lines; this follows that shape while carrying the search
phrases.

```
Download every Canvas course in one run
Sync new and changed files with one click
Daily auto-sync, with a Today page for what arrived
Sync Review: see every change before anything is written
Never overwrites a file you edited or annotated
Exports Canvas pages, assignments, announcements, quizzes and discussions
Downloads Panopto lecture recordings as MP4 or MP3
On-device lecture transcripts and subtitles, nothing uploaded
Converts PowerPoint, Word and Excel to PDF for NotebookLM and other AI tools
Searchable directory of 4,750+ verified Canvas schools
Runs entirely on your own PC: no account, no server, no telemetry
Free and open source, GPL-3.0
```

Partner Center bullets these itself. **Do not add your own bullet characters.**

### 3.6 Keywords  -  7 terms, 20 of 21 words

Limits: up to 7 terms, 40 characters each, **no more than 21 separate words in
total**. Not shown to customers. Chosen from the rank measurements in section 2.

```
canvas course downloader
download canvas files
panopto lecture recordings
notebooklm study files
canvas sync
bulk course download
lecture transcripts subtitles
```

One spare word remains. Leave it: it is headroom for a term that a future
search-term report proves, and a keyword added on a hunch can only dilute.

### 3.7 The GPL-3 fields  (this is the licence-compliance step)

**Additional license terms** - enter this URL **on its own**, nothing else, so
Partner Center renders it as a clickable link:

```
https://github.com/BrkBuilds/Canvas-Downloader
```

**Copyright and trademark info** (200 char limit) - drop the year so it does not
need touching again, and name the licence:

```
(c) BrkBuilds. Licensed under GPL-3.0-or-later. Not affiliated with Instructure, Inc. or Canvas LMS.
```

Together with the scheme-less mention in the description and the `LICENSE` +
`THIRD_PARTY_NOTICES.md` files inside the package, this discharges GPLv3
section 6. `THIRD_PARTY_NOTICES.md` is what covers the bundled GPL FFmpeg build.

### 3.8 The three URL fields  (fixes section 1.1)

| Field | Set it to |
|---|---|
| Privacy policy URL | `https://canvasdownloader.app/privacy.html` |
| Website | `https://canvasdownloader.app/` |
| Support contact info | `https://github.com/BrkBuilds/Canvas-Downloader/issues` |

All three verified 200 on 2026-08-24. **Re-verify with `curl -sI -L` before
submitting**, not by eye: the failure this fixes was invisible from reading.

#### The out-of-repo URL checklist  (run this after ANY account or domain rename)

`tests/test_no_stale_repo_urls.py` sweeps the repository for stale links, and it
passed the whole time these two were dead, because Partner Center is not a file.
These are the published surfaces a grep cannot see. Resolve each and require
**200**:

```bash
# 1. read the three fields back off the LIVE listing
curl -s "https://storeedgefd.dsx.mp.microsoft.com/v9.0/products/9n1dwwvrq5wc?market=US&locale=en-US&deviceFamily=Windows.Desktop" > store.json
python -c "import json;p=json.load(open('store.json'))['Payload'];print(p['PrivacyUrl']);print(p['AppWebsiteUrl']);print([u['Uri'] for u in p['SupportUris']])"

# 2. resolve whatever came back
curl -sI -L "<url>" -o /dev/null -w "%{http_code} %{url_effective}
"
```

Also check by hand: the **GitHub repo's own About / homepage field**, and any
**directory listing** (AlternativeTo, Softpedia). None of them is in the repo.

**Why a spot check fails here.** GitHub redirects a renamed *repository* for ever
but does not redirect `<olduser>.github.io` after a *username* change. So the
`github.com` support link kept working while both Pages links died. Checking one
link reports all clear.

---

## 4. THE SCREENSHOTS

Source: `G:\6 projekter\Canvas Downloader\1 MS_Store BILLEDER\`

All eight verified against the real requirements: **1920x1080 PNG, 16:9,
1.0-1.7 MB, fully opaque** (alpha min 255, so nothing can composite oddly on the
Store's background). Limits are 1366x768 minimum, PNG, 50 MB, 10 maximum.

**Replacing all nine old ones is the right call.** The old set is raw v2.0.0
grabs: the version string is legible in the corner, the app content fills only
the top half of several frames, the UI text is unreadable at carousel size, and
they predate the step tracker and the institution picker.

### Order, and why it is this order

The evidence is consistent across ASO research: **the first three do almost all
the work** and users rarely scroll past them. So slots 1-3 must land *what it
is*, *how little effort it takes*, and *the thing no competitor does*.

| # | File | Why here |
|---|---|---|
| 1 | `CD_MSStore_1_Download2.png` | The core promise, in the app, in four words |
| 2 | `CD_MSStore_2_Quick_Download_preset.png` | Kills the "this looks complicated" objection immediately |
| 3 | `CD_MSStore_3_AI_Conversions.png` | The NotebookLM angle - the fastest-growing arrival moment and the least contested |
| 4 | `CD_MSStore_6_Panopto.png` | Lecture recordings. Highest-volume distinct use case; also the visual break in the run of blue |
| 5 | `CD_MSStore_4_SyncReview.png` | Sync, and the safety guarantee |
| 6 | `CD_MSStore_5_Today.png` | Auto-sync, the reason it stays installed |
| 7 | `CD_MSStore_7_Download_Log.png` | Proof it is a real working app |
| 8 | `CD_MSStore_8_final.png` | Trust close: no account, no telemetry, open source |

**Slot 4 is a deliberate change from source order.** Panopto is a *different
person's* reason to install, not a deeper version of the first three, so it is
placed where a viewer who was not sold by 1-3 still meets it. It also breaks the
blue run, which stops the carousel reading as one long image.

### Captions  (200 char limit each, currently empty on all nine)

```
1  Tick your courses and download all of them in one run. Custom Download for exact control, or Quick Download to pick a preset and go.

2  Five ready-made setups, no configuration. "AI & NotebookLM Ready" converts everything as it downloads, so the folder is ready to drop into a study tool.

3  Eight automatic conversions. PowerPoint, Word and Excel become PDFs, Canvas pages become plain text, archives unpack, and video becomes audio.

4  Save Panopto lectures as video, audio, a transcript or subtitles. Transcription runs on your own computer, so no recording is ever uploaded.

5  Sync Review compares your folder against Canvas and sorts every difference: new, updated, edited by you, deleted. Nothing is written until you choose.

6  Switch on daily sync and new course files arrive by themselves, the first time you open the app each day. Today shows you exactly what turned up.

7  Live progress across every course, with speed, file count and time remaining. Cancel whenever you like and keep everything already saved.

8  No account, no server, no telemetry. Sign in with a token you create yourself, find your university in the built-in directory, and it all stays on your PC.
```

### Three things to fix in the images before uploading

Found by reading them at full size. None blocks submission; the first is worth
ten minutes because it is on the frame most people see.

1. **Typos, all the same class - a lowercase word that should be capitalised.**
   - `1_Download2`: **"On your pc"** -> **"On your PC"**. This is slot 1, the
     single most-viewed frame in the listing.
   - `5_Today`: **"Newest canvas files."** -> **"Canvas"**, and
     **"on your pc."** -> **"On your PC."** (it also begins a sentence).
   - `4_SyncReview`: **"what's on canvas."** -> **"Canvas"**.

   Canvas is a proper noun *and* the product you are naming. Lowercasing it in
   the hero text of a Canvas tool is the one typo a reader in this audience
   notices.

2. **`3_AI_Conversions` carries third-party logos** (NotebookLM, ChatGPT,
   Gemini, Claude). Showing compatibility is normal and generally accepted, and
   the app genuinely produces files for those tools - but Store certification can
   query third-party marks that imply endorsement. **Low risk, non-zero.** If it
   is ever queried, the fix is to keep the frame and drop the logo strip; the
   words carry the meaning on their own. Do not pre-emptively remove it.

3. **`7_Download_Log` shows `SPEED 0.0 MB/s` mid-download.** A true captured
   instant, but at a glance it reads as stalled on the one frame whose whole job
   is to prove the thing works. Optional, and only if the source file is still
   editable.

---

## 5. THE 16:9 SUPER HERO ART  (currently empty - the biggest missing asset)

**1920x1080 or 3840x2160 PNG.** It becomes the main image at the top of the
listing on Windows 10 and 11, it is what the Store uses in promotional layouts,
and providing it is what makes the app eligible to be considered for featured
placement. It is also a **prerequisite for trailers appearing at the top** of the
listing.

### The rules, and they are strict

- **No text at all**, and specifically no product title.
- **No app UI**, and no device-specific imagery (no laptop bezels, no phones).
- **Nothing important in the bottom third** - a gradient is applied there.
- **Key detail centred** - the image gets cropped in some layouts.
- **Minimise empty space.** Half a frame of flat blue will look broken.
- Dynamic and specific to the app. No stock photography, no generic visuals.
- No flags, national or political themes, religious symbols, weapons, gambling.

Note how much of that the existing carousel violates by design: every frame has
text and app UI. **The hero art cannot be a crop of one of them.**

### Four concepts

**A. The file cascade  (recommended)**
A dense, glowing stream of document icons - PDF, PPTX, DOCX, XLSX, MP4 - flowing
diagonally out of an abstract glowing portal or cloud form on the left, arcing
through the centre, and pouring into an open folder on the right. Deep brand-blue
gradient, the same 3D glass file icons already floating in frames 1 and 5.

*Why this one:* it is the product as a picture - many scattered things becoming
one organised thing - with no word needed. It reuses the visual language the
carousel already established, so the page reads as one designed system. It is
centre-weighted, so it survives cropping, and the density requirement is easy to
meet.

**B. The folder shelf**
An overhead, slightly tilted view of many course folders in neat receding rows,
each with a soft glow, disappearing into blue depth. Says "all of it, ordered".
*Risk:* repetition can read as a texture rather than a subject, and it is the
concept most likely to look like stock.

**C. The single folder, opening**
One hero folder, dead centre, lid lifted, light pouring out, file icons rising
and drifting up out of it. *Why consider it:* strongest at small crop sizes and
closest to the app icon, so it reinforces brand recognition in a grid of Store
tiles. *Risk:* the least informative of the four.

**D. Before / after split**  -  **do not use**
Chaotic scattered documents on the left, tidy stacked folders on the right,
bright seam down the middle. It is the most persuasive idea and it **fails the
crop rule**: any centre crop cuts the seam and destroys the whole point. Recorded
so it is not re-proposed.

If you want a hedge: build **A**, and keep **C** as the fallback if A looks busy
once the bottom third is dimmed.

---

## 6. THE TRAILER

Up to 15 allowed; one is plenty. **It only appears at the top of the listing if
the 16:9 Super hero art exists**, so build that first.

Expect an install lift in the region of **10-30%** from a good one - and a
**10-15% loss** from a bad one. This is not a "ship it and see" asset.

### Technical requirements (hard)

| | |
|---|---|
| Format | MP4 (H.264 / AVC1) or MOV |
| Resolution | **exactly 1920 x 1080** |
| Length | 60 seconds or less recommended |
| File size | under 2 GB |
| Video | High Profile, progressive (no interlacing), closed GOP of half the frame rate, CABAC, up to 50 Mbps, 4:2:0 |
| Audio | AAC-LC, stereo, 48 kHz, 384 kbps |
| Container | `moov` atom at the front (Fast Start), no edit lists or you lose A/V sync |
| Thumbnail | separate **PNG, 1920 x 1080** - use a still from the video, not a carousel frame |
| Title | 255 characters or fewer |
| Captions | optional WebVTT `.vtt`, under 50 MB |

**Audio must be AVC1-encoded H.264 or some viewers hear nothing.** That is
Microsoft's own warning, and it is the failure you cannot see when you check
your own upload.

### What to focus on

Snappy but calm, live walkthrough, bold text overlays and subtitles matching the
carousel is the right instinct, and it matches what the research says. Four
things to build around:

1. **Viewers decide in the first 3 to 5 seconds.** Do not open on a logo
   animation or an empty app. Open *mid-action*, on the moment that is only
   possible with this app: the course list with every box ticking on.
2. **Assume it is watched with no sound.** Music can carry mood; it cannot carry
   meaning. Every claim needs to be legible on screen. The text-overlay plan
   already covers this - keep the overlays on long enough to read at a glance,
   which is longer than it feels while editing.
3. **Key information belongs in the CENTRE of the frame.** Some Store layouts
   crop the top and bottom. Do not put the overlay text near the edges.
4. **Real captured UI only.** No mocked-up screens and no marketing overlays
   that misrepresent behaviour.

### A beat sheet, roughly 45 seconds

Not a script. What must be on screen, and for how long.

| Time | On screen | The point |
|---|---|---|
| 0:00-0:04 | Course list, checkboxes ticking on in sequence, counter running up to "15 of 15 selected" | The hook. Motion in frame 1, and the promise is legible instantly |
| 0:04-0:09 | Quick Download pressed, preset picked, run starts | It takes two clicks |
| 0:09-0:17 | Download progress: course counter climbing, file names streaming, MB and time remaining moving. **Speed up 2-4x** | It really does all the courses. This is the proof shot |
| 0:17-0:23 | Cut to Explorer. Scroll the finished course folders, open one, show the PDFs | The payoff is files on their disk, not a screen in an app |
| 0:23-0:30 | Back in the app: Quick Sync, small result, then Sync Review with its coloured categories | It stays current, and you stay in control |
| 0:30-0:37 | Panopto section, outputs ticked, then a transcript `.txt` opening in Notepad | Lectures, and the most surprising capability |
| 0:37-0:43 | Course folder dragged into NotebookLM | The modern reason to want any of this |
| 0:43-0:45 | App icon, then one still card: no account, no telemetry, free, open source | The close, and the objection answered last |

**Two things to leave out.** The login screen and the access-token setup: it is
the least exciting part of the product and the only part that looks like work.
And any real course names or a real institution - blur them or use a test
account.

**Thumbnail:** pick the frame at roughly 0:12, mid-download with the numbers
moving. It is the frame that proves the app is real.

---

## 7. THE SUBMISSION  (step by step)

The package is already built and verified. Do not rebuild it.

### 7.0 Before you start - verify the package once more

```bash
ls -la msix_output/CanvasDownloader_2.0.2.0.msix
```

Verified 2026-08-24: **135.7 MB**, **unsigned** (correct - the Store signs it),
`Name="BrkBuilds.CanvasDownloader"`, `Publisher="CN=BE7EDB0D-73AD-43BE-B143-F68AB08998C3"`,
`Version="2.0.2.0"`, 4,804 files, **0 `__pycache__` directories**, bundles the
GPL-3 `LICENSE` and `THIRD_PARTY_NOTICES.md`, `version.py == 2.0.2`.

Built from `dist/Canvas Downloader/`, which is byte-equivalent to the **v2.0.2
tag** for everything that ships: the only `.py` difference between the tag and
`HEAD` is `scripts/sync_release_page.py`, which is not bundled. That satisfies the
GPL duty that "which source produced this binary" has an answer.

**Never sign it yourself.** A self-signed package cannot be submitted.

### 7.1 Create the submission

Partner Center -> **Apps and games** -> **Canvas Downloader** -> **Start a new
submission** (it clones the live one, so every field below is an edit, not a
blank form).

### 7.2 Packages

Upload `msix_output/CanvasDownloader_2.0.2.0.msix`.

**Partner Center retires the old package by itself. Click nothing.** Once
2.0.2.0 validates, 2.0.0.0 appears struck through with *"This package will be
removed after you save this page"*, and the ranking table shows **2.0.2.0 as
rank 1**, 2.0.0.0 as rank 2. That is the correct end state; save and continue.

**DO NOT click either link on that screen** (verified against the real page,
2026-08-24):

- **`Remove`**, at the bottom, sits directly under the **2.0.2.0** block and
  removes the package you just uploaded. An earlier draft of this step said
  "remove the old 2.0.0 package", which combined with that layout is precisely
  how the wrong one gets removed.
- **`Don't remove this package`**, inside the warning, KEEPS 2.0.0.0 alongside
  the new build. Leaving both is how users go on being served the old one.

Before saving, confirm the page agrees with the manifest: ranking **2.0.2.0 = 1**,
both rows **X64**, device family **Windows.Desktop min version 10.0.17763.0**.

#### The two checkboxes below the package list - leave BOTH unchecked

**"Make this update mandatory" is inert for this app**, on two independent
grounds. Microsoft's own warning on the control says it applies only to **UWP**
packages, and this is a full-trust Win32 app (`EntryPoint =
Windows.FullTrustApplication`, capability `runFullTrust`). And even for a UWP
package the flag is only a *signal* the app reads back via
`StoreContext.GetAppAndOptionalStorePackageUpdatesAsync()` and acts on itself -
this app makes no Store API calls at all, because WinRT bindings were
deliberately kept out of the bundle (see `core/store_review.py`). Ticking it
would change nothing while implying to a later reader that updates are forced.

**"Roll out update gradually" is a mechanism for limiting blast radius while you
WATCH for a problem, and there is nothing here to watch with.** No analytics and
no telemetry is a settled decision in `STRATEGY.md`, so a staged rollout is a
delay rather than a safety net. It also has to be finished by hand: forget, and
a fraction of users sit on the old version indefinitely - the same failure the
package removal above exists to prevent. And this update carries the data-loss
fixes, so delaying it has its own cost.

The one honest argument for staging is that **the MSIX has not been
sideload-tested** - the binary is the same one shipping as the `.exe`, but
container behaviour (WebView2, Office COM, keyring, `%APPDATA%` writes) is what
`msix/README.md` says the sideload test is for. Answer that by running the test,
not by hedging with a mechanism you cannot observe: `python build_msix.py --test`
builds a separate self-signed `CanvasDownloader.Dev` package that cannot disturb
the real listing.


### 7.3 Properties

- **Category:** Education > Study guides. **Keep it.** It is accurate, the
  audience browses it, and Productivity is far more competitive for no gain.
- **Privacy policy URL** -> `https://canvasdownloader.app/privacy.html`
- **Website** -> `https://canvasdownloader.app/`
- **Support contact info** -> `https://github.com/BrkBuilds/Canvas-Downloader/issues`

These three are section 1.1. **Do not skip them because they look filled in.**

### 7.4 Store listing (English (United States))

Paste sections 3.2, 3.3, 3.4, 3.5 in order. Then:

- **Screenshots:** delete all nine, upload the eight from section 4 in the order
  given, and add a caption to each. Order is set by drag and drop after upload.
- **Store logo (1:1 app tile, 300x300):** optional but the Store prioritises it
  over the package logo. `assets/icon.png` scaled to 300x300 will do.
- **16:9 Super hero art:** section 5, if it is ready. If not, submit without it
  and add it in the next submission - do not hold the update for it.
- **Trailer:** only if the hero art is present.

### 7.5 Additional information

- **Keywords:** the 7 from section 3.6.
- **Additional license terms:** the URL from section 3.7, on its own.
- **Copyright and trademark info:** the line from section 3.7.

### 7.6 Submit

Certification typically takes a few hours to a couple of days. Age rating and
pricing are already set and do not need touching.

### 7.7 After it goes live - verify, do not assume

```bash
curl -s "https://storeedgefd.dsx.mp.microsoft.com/v9.0/products/9n1dwwvrq5wc?market=US&locale=en-US&deviceFamily=Windows.Desktop"
```

Check `PrivacyUrl`, `AppWebsiteUrl` and `SupportUris` resolve **200**, that
`Description` is the new text, and that `Notes` no longer says v2.0.0. This is
the same call that found the 404s; it is the cheapest possible regression test
and it takes one command.

Then re-run the rank measurements in section 2 in about two weeks and record the
deltas here. Keywords take time to take effect and an unmeasured change teaches
nothing.

---

## 8. WHAT THIS UPDATE SWITCHES ON

**The in-app "rate on the Store" card is MSIX-only and ships in v2.0.2.** It has
never run in the Store build, because the Store build is v2.0.0 and predates it.
FINDINGS calls the rating prompt *"the highest-value item"*: the Store listing has
**0 ratings after 800+ installs**, Store ranking is rating-driven, and nearly
every app outranking us in adjacent queries sits between 4.0 and 4.8 stars.

The gate is `shared/helpers.is_msix_package()`, which asks Windows via
`kernel32.GetCurrentPackageFullName`. `CLAUDE.md` recorded it as **not verified
in a packaged build**. **Verified 2026-08-24** with both controls, on Windows,
using the exact call from the real function:

```
unpackaged system python     rc = 15700 (APPMODEL_ERROR_NO_PACKAGE) -> False   [negative control]
Store-packaged Python 3.11   rc = 122   (ERROR_INSUFFICIENT_BUFFER) -> True    [positive control]
                             package full name: PythonSoftwareFoundation.Python.3.11_3.11.2544.0_x64__qbz5n2kfra8p0
```

**The negative control is the half that matters**: a gate that answers True for
everything would show the card on the `.exe` build too, and a gate that answers
False for everything would silently never show it at all. Both are excluded.

**What is still unverified** is the *card rendering* inside a real MSIX
container - the gate is proven, the surface it gates is not. The honest check is
`python build_msix.py --test` plus a sideload, per `msix/README.md`. It is worth
doing at some point, but it is **not a blocker for this submission**: the failure
mode is one card not appearing, and the rest of the app is the same binary that
already ships as the `.exe`.

---

## 9. WHAT WAS DELIBERATELY NOT DONE

Recorded so the next session does not re-derive these and quietly answer them
differently.

- **The Product Name was not extended with keywords.** Reasoning in section 2.
- **`bulk download` / `batch download` / `download manager` were left out of the
  keywords.** Download-through rate is a ranking signal, those searchers want a
  different product, and failed impressions cost us. Section 2.
- **The install count is not published in the listing**, only the country count.
  Section 3.3.
- **The `.exe` and macOS builds are not advertised in the Store description.** A
  Store visitor is on Windows and about to get the signed, auto-updating,
  SmartScreen-free build, which is the best outcome for them. The Website field
  covers anyone who needs the other platforms.
- **A macOS App Store listing is not planned.** It would require sandboxing this
  app cannot satisfy. `PLAYBOOK.md` settles this.
- **`3_AI_Conversions`'s third-party logo strip was not removed.** Section 4.
