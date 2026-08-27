# Playbook: off-site execution

Written 2026-08-20. Every claim here was measured or checked on that date, and
every link was requested and confirmed to resolve. Where something could not be
verified it says so rather than guessing.

Part of the marketing memory in this folder. See [README.md](README.md) for the
index, [FINDINGS.md](FINDINGS.md) for what is already known and decided,
[STRATEGY.md](STRATEGY.md) for the rules that govern the copy below, and
[SITE_RUNBOOK.md](SITE_RUNBOOK.md) for anything touching `docs/`.

This is an internal document. It is **not** in `docs/`, so it is not published.

---

## 1. Where you actually stand

Measured, not estimated:

| Fact | Value | How it was checked |
|---|---|---|
| Homepage TTFB | 186 ms | Chromium navigation timing, live site |
| LCP, desktop unthrottled | 1068 ms (good) | PerformanceObserver |
| **LCP, mobile 4x CPU / 1.6 Mbps** | **5300 ms (POOR)** before the fix, **2764 ms** after | PerformanceObserver, 390px mobile profile |
| Cumulative Layout Shift | 0.0057 desktop, 0.0219 -> 0.0013 mobile | PerformanceObserver (good is < 0.1) |
| Page weight | 5.36 MB, of which **4.70 MB was autoplaying demo video** loaded before the hero image | 18 requests, full scroll |
| Analytics on the site | none | grep for 11 vendors across all pages |
| GitHub | 1 star, 0 forks, 0 watchers, Discussions off | GitHub API |
| Repo age | created 2026-01-17 | GitHub API |
| Domain appearances in 3 web searches | **zero** | see below |

**The finding that matters.** Three searches were run: `"canvas downloader" app
download all canvas courses`, `canvasdownloader.app Canvas Downloader free
desktop app Windows macOS`, and a `site:` query. `canvasdownloader.app` appeared
in **none** of them. The Microsoft Store listing appeared in two, and when the
search assistant summarised "Canvas Downloader" it **quoted your Store copy**.

So today the Store listing is your entire discovery surface and the website is
invisible. That is not a page-quality problem, since the pages are technically
sound. It is an authority problem: a domain that is months old with effectively
no inbound links, competing for a phrase that other products already own.

**What you are competing with for the name.** Verified live:

- [canvasdownloader**.com**](https://www.canvasdownloader.com/) is a Spotify
  Canvas downloader. Different product, much higher search volume, owns the .com.
- [Canvas Downloader - Bulk Save Course Files](https://chromewebstore.google.com/detail/canvas-downloader-bulk-sa/odmemmdfgbjocanojmocjdbanbhimkeh),
  a Chrome extension with your exact name.
- [Canvas Course Downloader](https://chromewebstore.google.com/detail/canvas-course-downloader/mmnmcnffbkcnhcjiidmdnaclpfeekiol)
  and [Canvas Course Downloader (Simple)](https://chromewebstore.google.com/detail/canvas-course-downloader/obbocioaimahikkffknmllfmmgggmkmf).
- Five GitHub repos with the same name, all outranking yours:
  [jamubc](https://github.com/jamubc/Canvas_Downloader),
  [aik2mlj](https://github.com/aik2mlj/canvas-downloader),
  [beast-nev](https://github.com/beast-nev/canvas-downloader),
  [RoryQo](https://github.com/RoryQo/Canvas-Course-Downloader),
  [BenSweaterVest](https://github.com/BenSweaterVest/Canvas-Downloader).

**Who owns the money query.** For "how to download all files from Canvas at
once", the results are university help desks:
[Stanford](https://canvashelp.stanford.edu/hc/en-us/articles/115001602467-Bulk-download-Canvas-files),
[Illinois](https://answers.uillinois.edu/illinois/page.php?id=127046),
[Clemson](https://hdkb.clemson.edu/phpkb/article.php?id=939),
[Pitt](https://teaching.pitt.edu/resources/how-to-export-course-materials-from-canvas/),
[NCTC](https://ecampushelpdesk.nctc.edu/hc/en-us/articles/205334770-Downloading-multiple-files-from-Canvas-to-your-PC),
[UNT](https://lms.unt.edu/resources/canvas-eos-tasks.html).

You will not outrank a `.edu` on a young domain. You do not have to. Every one
of those pages stops at the same wall, and that wall is your product pitch.
`docs/how-to-download-all-canvas-files.html` is written to stand beside them
rather than against them.

---

## 1b. Do these five things yourself, first

None of these can be done from the repo, all are quick, and the first one is
actively costing you traffic today.

> **STATUS 2026-08-23. Three of the five are done; do not redo them.**
>
> | # | Item | State |
> |---|---|---|
> | 1 | Release-note dead links | **done** 2026-08-21, on v2.0.1, v2.0.0 and v1.0.0 |
> | 2 | Social preview | **still open, and it is a different defect than described below** - the preview IS set and points at a deleted image (404), which is why an upload appears not to take. Remove the image FIRST, then upload. Full diagnosis in FINDINGS.md |
> | 3 | Bing Webmaster Tools | **open** - the only one nobody has touched |
> | 4 | Search Console | **done**, and it answered the indexing question: the site is indexed |
> | 5 | GitHub Discussions | **done**, enabled 2026-08-21 |
>
> The text below is the original brief, kept because its exact replacement URLs
> and reasoning are still the record of what was done.

### 1. Fix the v2.0.1 release notes (10 minutes, highest value)

The release page is where people who click "Releases" land, and Google indexes
it. Its notes contain **five dead links**, all created by the move to the
BrkBuilds organisation:

```
https://birkls.github.io/Canvas_LMS_batch_file_downloader/              -> 404
https://birkls.github.io/Canvas_LMS_batch_file_downloader/guide.html    -> 404
https://birkls.github.io/Canvas_LMS_batch_file_downloader/privacy.html  -> 404
https://birkls.github.io/Canvas_LMS_batch_file_downloader/mac-setup.html-> 404
https://github.com/birkls/Canvas_LMS_batch_file_downloader/issues       -> redirects, but stale
```

The github.com one still redirects because GitHub forwards a renamed owner. The
four `github.io` ones do **not**: a project Pages site stops existing when you
move to a custom domain, so the headline "Website & guides" link at the top of
your most important release page is a hard 404.

`scripts/migrate_repo_urls.py` could not catch these because release notes live
on GitHub, not in the tree. Edit the release at
[github.com/BrkBuilds/Canvas-Downloader/releases/tag/v2.0.1](https://github.com/BrkBuilds/Canvas-Downloader/releases/tag/v2.0.1)
and replace them with:

```
https://canvasdownloader.app/
https://canvasdownloader.app/guide.html
https://canvasdownloader.app/privacy.html
https://canvasdownloader.app/mac-setup.html
https://github.com/BrkBuilds/Canvas-Downloader/issues
```

Also worth correcting while you are in there: the notes name the Windows asset
`Canvas_Downloader_Setup_2.0.1.exe`, but the attached file is actually
`Canvas_Downloader_v2.0.1_Windows.exe`.

v2.0.0 and v1.0.0 carry stale `github.com/birkls/...` links too. Those redirect,
so they are lower priority, but a released GitHub username can be claimed by
somebody else, at which point they stop being harmless.

### 2. Set the GitHub social preview image

`docs/assets/github-social-preview.png` exists and is exactly the right size
(1280x640, verified), and the repo is **not using it**. The API reports no
custom Open Graph image, so every time your repo link is pasted into Discord,
Slack, X or Reddit, GitHub renders a generic auto-card instead of the one you
designed.

Repository **Settings > General > Social preview > Upload an image**.

### 3. Set up Bing Webmaster Tools

Not set up. It can import from Search Console in one click, and it feeds Bing,
DuckDuckGo and Copilot. Worth more than its market share suggests, because
several AI assistants are Bing-backed.

### 4. In Search Console, answer one question

Submit `https://canvasdownloader.app/sitemap.xml`, then open **Pages** and find
out **whether the site is indexed at all**. I could not determine that from
outside: three web searches naming the domain returned nothing, but that is
consistent with both "not indexed" and "indexed and ranking nowhere". Search
Console answers it definitively, and the two answers need completely different
responses.

Then use URL Inspection on the two new guide pages to request indexing directly.

### 5. Consider enabling GitHub Discussions

Currently off. It creates indexable question-and-answer content on a
high-authority domain that links back to you, and it gives users somewhere to
go that is not the issue tracker. Low effort, compounding.

## 2. The one rule

**Be the most useful answer in the room, then say what you built.** Every
channel below fails if you invert that order, and forums punish it permanently.
Three specifics that are not optional:

1. **Disclose that you made it, every time.** "I built this" costs you nothing
   and is the difference between a contribution and a removed post.
2. **Answer the question first**, completely, including the parts your app does
   not solve. If the honest answer is "use Canvas's own Download as Zip", say
   that.
3. **Never post the same text twice.** Copy-paste across threads is the single
   clearest spam signal a moderator has.

---

## 3. Priority 1: three community threads, this week

These are real, open threads that rank for your query. Verified 2026-08-20.

### 3a. The best one

**[STUDENT QUESTION: How do I backup/download a course as a student who does not
own the course?](https://community.instructure.com/en/discussion/619809/student-question-how-do-i-backup-download-a-course-as-a-student-who-does-not-own-the-course)**
(Instructure Community, Oct 2024)

The asker is exactly your user. Her words: *"I would like to download all course
content that was available to me as a student so that I can keep it after I
graduate. I'll likely lose access to my two-factor authentification... I've paid
thousands of dollars to access this material."*

The single accepted answer is *"You really should speak with your instructor
first and ask for permission to do this."* That is fair advice and it answers
nothing about the how. The thread has been sitting there since October 2024.

Draft reply (edit it, do not paste it verbatim):

> Susan is right that the permission question comes first, and it is worth
> checking your syllabus, because some courses have an explicit policy.
>
> On the how: students cannot export a course. The `.imscc` course export is an
> instructor permission, so you will not see the option. What you can do
> yourself:
>
> 1. **Per course**, open Files in the course nav, click in the list, press
>    Ctrl/Cmd+A and choose Download as Zip. Two caveats: a file attached
>    directly to a module item does not have to appear in the Files tab, so the
>    zip can silently miss material, and teachers can hide the Files tab
>    entirely.
> 2. **Your own submitted work**, via Account > Settings > Download Submissions
>    > Create Export. It covers concluded courses too. It does not include
>    instructor-annotated versions, which is worth knowing if the annotated
>    copy is the one you care about.
> 3. **Pages, assignment briefs, announcements and discussions** have no bulk
>    export at all. Saving each as a PDF from your browser is the manual route.
>
> On your 2FA point specifically: losing the second factor is not usually what
> ends access. Enrolments are removed on their own schedule and the course can
> disappear while your login still works, so the safe assumption is that you have
> less time than you think.
>
> Full disclosure, I wrote a free open-source app that does the above through
> the Canvas API, including the categories Canvas has no export for. It needs an
> access token, which some institutions have disabled, so check that you can
> create one under Account > Settings before you count on it. Happy to point you
> at it if it is useful, and the manual routes above work regardless.

### 3b. The one that ranks

**[How to download all course files and media on
Canvas](https://community.instructure.com/en/discussion/618390/how-to-download-all-course-files-and-media-on-canvas)**
(Oct 2024). This one surfaces in Google for the main query. Two accepted
answers, both partial. One ends: *"As for Pages and Assignments, I'm not sure of
a quick way off the top of my head."*

The asker also says their school **removed access tokens**, so lead with the
methods that do not need one. Answering the Pages and Assignments half is a
genuine contribution to a thread that never got one.

### 3c. Do NOT answer this one

**[How to I download ALL the files from my Canvas course to my
computer?](https://community.instructure.com/en/discussion/633259/how-to-i-download-all-the-files-from-my-canvas-course-to-my-computer)**
(Feb 2025). The asker is tagged **Instructor**, and the accepted answer is the
course export they already have access to. Your product is not the answer here
and posting it would read as spam. Listed so it is not mistaken for a target.

---

## 4. Priority 2: directory listings

Ready-to-paste copy is in section 7. Notes on each:

| Where | Link | Notes |
|---|---|---|
| AlternativeTo | [alternativeto.net](https://alternativeto.net/) | **Submitted 2026-08-27.** Highest value here: people search it for "alternative to X". Listed as an alternative to the Chrome extensions above. Moderated, so see the note under this table before counting it. |
| Product Hunt | [producthunt.com/posts/new](https://www.producthunt.com/posts/new) | **Submitted 2026-08-27.** A product gets one post, and this was it, so the old "Tuesday to Thursday, 00:01 PT" timing advice is spent and no longer actionable. |
| ~~MajorGeeks~~ | [submit software](https://www.majorgeeks.com/content/page/submit_software.html) | **Ruled out 2026-08-27.** Submission is by email, the site is outdated, and the expected yield does not justify the effort. Do not re-add it on the strength of "still indexed well", which is what put it on this list. |
| Softpedia | [softpedia.com](https://www.softpedia.com/) | **Submitted 2026-08-27.** Already lists competing Canvas extensions, so the category exists. Softpedia is understood to re-host a mirror of the installer rather than linking the release; **verify what its download button actually serves** once the page is live, because a mirrored 2.0.2 goes stale and nothing here will say so. |
| GitHub topics | [canvas-lms](https://github.com/topics/canvas-lms), [canvas](https://github.com/topics/canvas) | Already done, your 20 topics are good. |
| ~~Slant~~ | [slant.co](https://www.slant.co/) | **Dead, confirmed 2026-08-27.** The 526 SSL error seen on 2026-08-20 was not transient. Do not spend time on it. |

**A submission is NOT a listing, and only a fetch settles it.** All three
submitted directories are moderated, so what exists today is a form that was
sent, not a page anyone can reach. This repo has already been wrong twice by
trusting a record over a fetch (the GitHub `og:image` whose record exists while
the blob 404s, and the Store's Privacy link that 404'd for ten weeks while a
link guard passed - both in [FINDINGS.md](FINDINGS.md)). So when each listing
appears, write its URL into this table and confirm it returns **200**, and while
you are there check two things the submission form does not guarantee: that the
licence reads **GPL-3.0** (see FINDINGS.md on the relicense) and that the
download points at the current release rather than a frozen mirror.

Also worth doing, no link needed: submit to the `awesome-*` lists that cover
education or student tools by opening a PR on the relevant repo.

---

## 5. Priority 3: communities

Verified to exist 2026-08-20. Subscriber counts could not be read reliably, so
check sizes yourself before choosing.

**Directly on topic:** [r/canvaslms](https://www.reddit.com/r/canvaslms/) is the
obvious first stop, though it skews toward instructors and admins.

**Students:** [r/college](https://www.reddit.com/r/college/),
[r/university](https://www.reddit.com/r/university/),
[r/GradSchool](https://www.reddit.com/r/GradSchool/),
[r/studytips](https://www.reddit.com/r/studytips/).

**Software:** [r/opensource](https://www.reddit.com/r/opensource/),
[r/software](https://www.reddit.com/r/software/),
[r/windowsapps](https://www.reddit.com/r/windowsapps/),
[r/macapps](https://www.reddit.com/r/macapps/),
[r/DataHoarder](https://www.reddit.com/r/DataHoarder/) (a genuinely good fit:
that audience cares about local copies and no cloud).

**Read each subreddit's self-promotion rule before posting.** Several ban it
outright, several allow it with a flair, and several allow it only from accounts
with existing history. Posting into a ban costs you the account.

**The highest-yield channel is not Reddit, it is your own university.** One post
in a course group chat, a study group or a student Facebook group reaches people
who have the exact problem today, and it needs no SEO at all.

---

## 6. Priority 4: the Microsoft Store

This is your only surface that currently ranks, and it is what AI assistants
quote. That makes it worth more attention than the website right now.

- **Store ranking is driven by ratings and installs.** You have no in-app prompt
  to rate. Adding one, shown after a genuinely successful run and never more
  than once, is probably the single highest-leverage change available. It was
  deliberately left unbuilt in this pass because it touches app screens whose
  layout has strict container rules and needs its own before/after check.
- **Keywords:** the Store has its own search. Make sure the description contains
  the literal phrases students type: "download all Canvas files", "bulk download
  Canvas course", "Canvas course downloader", "download Panopto lecture".
- **Do a macOS equivalent only if it is cheap.** The Mac App Store would require
  sandboxing that this app cannot satisfy, so the practical macOS channel is the
  website and Homebrew casks, not an app store.

---

## 7. Ready-to-paste copy

Vocabulary rule: students say **Canvas**, never "LMS". The only place "Canvas
LMS" appears is machine-readable schema. Directory listings get one clarifying
phrase because their audience is broader.

**Name:** Canvas Downloader

**One-liner (60 chars):**
```
Download every file from all your Canvas courses at once
```

**Short (150 chars):**
```
Free desktop app that downloads every file from all your Canvas courses at once,
then keeps the folders synced. Windows and macOS. Nothing leaves your computer.
```

**Medium (about 500 chars):**
```
Canvas Downloader gets every file out of your university's Canvas courses and
onto your computer in one run: module files, assignments, syllabus,
announcements, discussions, quizzes and the feedback on your own work. It then
keeps those folders up to date, fetching only what changed, and can save Panopto
lecture recordings as video, audio or a transcript. It converts Office files to
PDF so a course folder can be dropped straight into an AI study tool. Free, open
source, and it runs entirely on your own machine: no account, no server, no
telemetry.
```

**Long (directory listings):**
```
Canvas Downloader is a free, open-source desktop app for students who use
Canvas, the learning platform most universities run their courses on.

Canvas has no way to download everything. It can zip one course's Files tab at a
time, and that tab often does not contain files a lecturer attached directly to
a module. Nothing in Canvas exports Pages, assignment briefs, announcements,
discussions or quizzes at all.

Canvas Downloader signs in with an access token you create yourself and uses the
official Canvas API, so it can do what the built-in tools cannot:

- Download every file from every course you pick, in one run
- Collect the categories Canvas has no export for, saved as readable documents
- Sync: run it again and it fetches only what is new or changed, never
  overwriting a file you annotated and never restoring one you deleted
- Sync your chosen courses automatically once a day
- Save Panopto lecture recordings as MP4, MP3, a transcript or subtitles, with
  transcription running on your own machine
- Convert Word, Excel and PowerPoint to PDF, and unpack archives, so a course
  folder is ready for AI study tools

Windows 10/11 and macOS 14+ on Apple Silicon. Open source, GPL-3.0 licensed. No account, no
server, no telemetry, nothing uploaded. It reads only what your own Canvas
account can already open.
```

**Tags:** canvas, canvas-lms, student-tools, education, downloader,
batch-download, offline, sync, panopto, transcription, notebooklm, edtech,
open-source, windows, macos

**Product Hunt tagline (60 chars max):**
```
Get every file out of Canvas before you lose access
```

**Product Hunt first comment (post it yourself, immediately):**
```
Hi all, I built this because Canvas has no way to download everything. It zips
one course's Files tab at a time, and that tab frequently does not include the
slides a lecturer attached straight to a module. Pages, assignment briefs and
announcements have no bulk export at all.

I was about to lose access to four years of coursework and doing it by hand was
going to take a weekend. So: pick your courses, it downloads all of them,
including the parts Canvas will not export. Run it again next week and it fetches
only what changed, and it will never overwrite a PDF you annotated.

It runs entirely on your own machine. No account, no server, nothing uploaded,
and every line of it is on GitHub. It signs in with a Canvas access token you
create yourself, so it only ever reaches what your own account can already open.

Happy to answer anything, including what it does not do.
```

---

## 8. What to measure, given you chose no analytics

You picked Search Console and Bing Webmaster only, so the funnel below the click
is invisible by design. Accept that and measure what you can:

1. **Google Search Console** is already verified (the meta tag is on the
   homepage). Submit `https://canvasdownloader.app/sitemap.xml` and use the URL
   Inspection tool on the two new guide pages to request indexing directly.
   **First thing to check: whether the site is indexed at all.** I could not
   determine that from outside; Search Console answers it definitively under
   Pages.
2. **Bing Webmaster Tools** is not set up. Do it: it feeds Bing, DuckDuckGo and
   Copilot, and it can import from Search Console in one click. Bing matters more
   than its market share suggests because it backs several AI assistants.
3. **GitHub release download counts** are a real conversion number, free, and
   already on your README badge. The Microsoft Store dashboard gives installs.
4. **The proxy for everything else** is Search Console impressions on the two
   new pages. If they climb, the content strategy is working; if they do not
   after ~8 weeks, the pages need better targeting, not more pages.

---

## 9. Calendar

The demand for this product is seasonal and the peaks are predictable:

- **Late April to early June** and **late November to December**: end of
  semester and graduation. This is when "download Canvas before I lose access"
  peaks. Publish and promote before it, not during.
- **Late August to September**: new semester, new students setting things up.
  Good window for the "how to download all your files" page and for Reddit.
- **Exam periods**: the AI study-tools angle (NotebookLM, transcripts) is
  strongest here.

---

## 10. Things not to do

- **Do not buy links or submit to link farms.** A young domain with a sudden
  spike of low-quality links is the classic pattern that gets sites suppressed.
- **Do not spin up thin pages.** A page needs a distinct question and measured
  demand behind it; see [BLOG_PLAN.md](BLOG_PLAN.md). There is no cap on how
  many pages there should be.
- **Do not add analytics without updating `docs/privacy.html`.** You decided
  against analytics; if that changes, the privacy page has to change in the same
  commit or the site is making a false claim.
- **Do not chase the brand term yet.** The name is contested by a Spotify tool
  and three extensions. Long-tail phrases are winnable now and the brand term
  follows traffic, not the other way around.
- **Do not translate the site.** Your own verified institution list is 1,330 US
  schools against 9 Danish, plus 3,199 `.instructure.com` tenants that are
  predominantly US. English first is correct.

---

## 11. Still on the table, not done in this pass

Specified and ready to build, in value order:

1. **In-app "rate on the Microsoft Store"**, shown once after a successful run.
   Highest leverage of anything left, because Store rank is rating-driven.
2. **`download-panopto-lecture-recordings.html`.** A separate high-volume query
   you genuinely serve. Needs careful acceptable-use framing, since recordings
   are the material universities restrict most.
3. **`canvas-to-notebooklm.html`.** Current, low competition, and it is your
   clearest differentiator against every extension.
4. **`VideoObject` schema for the four demo videos.** Needs poster thumbnails
   generated first, which do not exist.
5. ~~Lazy-load the demo videos.~~ **Done 2026-08-20.** It turned out to matter
   far more than "mobile data": the four videos were requested ahead of the hero
   image, which is the LCP element, and mobile LCP was 5300 ms, inside Google's
   POOR band. Deferring them until the visitor approaches took it to 2764 ms.
   Note for anyone revisiting this: `preload="none"` does **not** work, because
   the browser ignores it while `autoplay` is present. Withholding the `src` is
   what works.
