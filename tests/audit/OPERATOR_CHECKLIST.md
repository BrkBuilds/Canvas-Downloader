# Operator checklist — v2.0.2 launch

Only the things **nobody else can do for you**: a browser session you are signed
into, a machine an agent cannot reach, or a decision that is yours.

Everything already done by the macOS session on 2026-08-21 is listed at the
bottom so you do not repeat it.

Ordered by *when*, not by size. Items 1–3 can be done today in any order and are
independent of the release; 4–8 are the release itself and are strictly ordered.

---

## STATUS 2026-08-23 — read this before working the list

| # | Item | State |
|---|---|---|
| 1 | Social preview | **open, and the diagnosis has changed** — see the rewritten item below |
| 2 | Search Console | **done.** The site IS indexed: `site:` returns 7 pages with real snippets, the sitemap is read, 11 pages discovered, and Google renders an AI Overview built from our own copy |
| 3 | Bing Webmaster Tools | **open** |
| 4 | Windows verification gate | **PASSED 2026-08-23.** Six findings, five test-side; one real product defect (the timeout adapter never applying its timeout). Suite 4413 passed / 0 failed, architecture audit clean |
| 5 | Build both installers | **both exist.** macOS DMG is on the v2.0.2 prerelease; Windows is at `installer_output/Canvas_Downloader_v2.0.2_Windows.exe` |
| 6 | Tag and publish v2.0.2 | **half done.** v2.0.2 is tagged and published **as a PRERELEASE**, macOS asset only. Attach the Windows exe and promote it to Latest |
| 7 | Update the website | **correctly untouched.** It advertises 2.0.1, which is right — `newest_shipped_version()` skips prereleases. It becomes wrong the moment 2.0.2 is promoted, so run the sync in the same sitting |
| 8 | Microsoft Store MSIX | **not started**, and it gates the launch date because certification takes days |

`gh` is now installed (2.98.0) but **not authenticated**, and step 7 needs it:
run `gh auth login` once.

---

## Today — independent of the release

### 1 · Repair the GitHub social preview (2 minutes, highest ratio)

**Settings → General → Social preview → Edit → REMOVE IMAGE first →**
then upload `docs/assets/github-social-preview.png`.

**The order is the fix.** Measured 2026-08-23: the repo's `og:image` points at
`repository-images.githubusercontent.com/…`, which is the CUSTOM-upload host
(an auto-generated card would be `opengraph.githubassets.com`), and that URL
answers **HTTP 404, `WebContentNotFound`**. GitHub holds a custom-preview record
whose image does not exist.

That single fact explains every symptom at once: the empty box in Settings, an
upload that "does not show up", and a shared link whose card image resolves to
nothing. Uploading over the dangling record is what has already been tried.
Remove it first.

This **corrects** the earlier note here, which said the preview was
`docs/icon.png` at 1024×1024. It is not — there is no image at all. The likely
cause is the `birkls` → `BrkBuilds` move orphaning the blob while leaving the
reference behind.

**Verify afterwards, because the Settings box cannot be trusted to show it:**

```bash
curl -s https://github.com/BrkBuilds/Canvas-Downloader \
  | grep -oE '<meta property="og:image"[^>]*>'
curl -sI "<that url>" | head -1        # must be 200, not 404
```

`200` with `Content-Type: image/png` is the pass; pasting the repo link into a
Slack or Discord message box is the visual check.

There is **no REST API** for this field, which is why it is yours and not mine.

Do it before any link goes anywhere. It is the image the launch is seen through.

### 2 · Google Search Console — answer the one open question

The verification meta tag is already on the homepage
(`google-site-verification: tNzz65…`), so the property should verify instantly.

Three things while you are in there:

- **Pages report.** This answers *"is the site indexed at all?"*, which
  `marketing/FINDINGS.md` calls the most important unanswered question in the
  folder. The two answers need opposite responses: *not indexed* is technical
  (fix crawling, request indexing); *indexed and ranking nowhere* is authority,
  and the answer is off-site work in `PLAYBOOK.md`. **Do not guess between them.**
- **Submit `sitemap.xml`.**
- **Request indexing** for the three newer guide pages.

Worth knowing: the no-JS fix shipped today removes one plausible cause — the
homepage's `h1` and 75% of its text, and 97% of the guide, were `opacity: 0` to
any crawler that does not run scripts. That is now measured at **0 hidden words
on the live site**. It does not tell you whether that cause was ever the
operating one; only Search Console does.

### 3 · Bing Webmaster Tools

One-click import from Search Console once #2 exists. It matters more than Bing's
market share suggests, because several AI assistants are Bing-backed — and the
register already records an assistant summarising this product from the Store
listing rather than from the site.

---

## The release — strictly in this order

### 4 · Windows verification (the gate)

Paste `tests/audit/WINDOWS_AUDIT_PROMPT.md` into a fresh agent on the Windows
PC. It is already on `main` and scoped to what actually changed — six ranked
areas, not "audit everything".

**Nothing below this line should happen until that agent says Windows is safe.**

Two things to hand it that it cannot know:

- how much free RAM the machine has (Office COM results are uninterpretable
  without it — the 2026-08-08 run had Excel hanging 180s per workbook purely
  from memory pressure, and a controlled re-run three hours later logged zero);
- whether you have WSL, which decides one open question in the brief.

### 5 · Build both installers

- **macOS**: run the `Build macOS DMG` workflow (`workflow_dispatch`). It builds
  from a fresh checkout, ad-hoc signs, and produces
  `Canvas_Downloader_v2.0.2_macOS.dmg`.
- **Windows**: `python scripts/build_windows.py` on the Windows box.

> **The rename trap.** The Windows build emits
> `Canvas_Downloader_Setup_2.0.2.exe`; the release asset is
> `Canvas_Downloader_v2.0.2_Windows.exe`. That rename is manual, and getting it
> wrong is exactly how v2.0.1's notes ended up naming a file that was not
> attached to it. Note the case too: the macOS workflow emits `_macOS.dmg`
> (lower-case *m*) while v2.0.1's asset is `_MacOS.dmg`. The releases page
> matches assets case-insensitively so the live page copes either way — but the
> static fallback href must match the real filename exactly.

### 6 · Tag and publish v2.0.2

`version.py` already says `2.0.2` and `version_info.py` is in sync — do **not**
bump either. `version.py` is deliberately kept *ahead* of every shipped tag,
because the in-app update banner compares the newest tag against the running
build; `tests/test_version_leads_tags.py` enforces that.

Write the notes with live links. The four dead ones on v2.0.1 are already fixed
(see below), so copy from the corrected version, not from an old draft.

### 7 · Update the website — only after the tag exists

**This is now one command, not seven hand edits:**

```
python scripts/sync_release_page.py --check    # show the drift
python scripts/sync_release_page.py            # rewrite
python -m pytest tests/test_website_advertises_shipped_version.py -q
```

It derives every fact from the ACTUAL release - tag, real asset names, real byte
sizes, real publish date - and regenerates the "Previous versions" baseline, so
none of it is typed. **Asset names are read, never constructed**, which is the
whole point: the Windows build emits `Canvas_Downloader_Setup_<ver>.exe` while
the release carries `Canvas_Downloader_v<ver>_Windows.exe`, and the macOS
workflow emits `_macOS.dmg` while v2.0.1's asset is `_MacOS.dmg` — a template
would be wrong on both counts, and that is exactly how v2.0.1's notes came to
name a file not attached to them.

Run `--check` **before** tagging too. It should say "already in sync", and that
is the control: a script that cannot reproduce the page as it stands has no
business writing the next one.

**Never do this before the tag.** The site must advertise what a visitor can
actually download; the register records the homepage once advertising a 2.0.2
nobody could get.

### 8 · Microsoft Store MSIX

`python scripts/build_msix.py`, then submit. Certification takes **days**, so
this gates your launch date rather than following it — start it the moment the
Windows gate passes, not after the marketing is written.

The Store is ~94% of all installs and the only surface of this product that
ranks today, and it has **0 ratings and 0 reviews** after 750+ installs. The
in-app "rate on the Store" prompt is still the highest-leverage unbuilt thing in
`marketing/PLAYBOOK.md`, and it is deferred for a good reason (it touches the
completion screens, which have strict container-inheritance rules). Worth doing
*after* launch, deliberately, not in the rush.

---

## Decisions only you can make

- **The in-app rate prompt** — build it or leave it. See above.
- **`canvas-to-notebooklm.html`** — deferred because its premise turned out to
  be partly false (NotebookLM added `.docx` support in Nov 2025). If you build
  it, frame it on what does not change: NotebookLM cannot reach your Canvas
  courses at all, free notebooks cap sources, and a lecture is far more useful
  to it as audio or a transcript than as an MP4.
- **The brand-name collision**, already settled as postponed.

---

## Already done for you (do not repeat)

| | |
|---|---|
| Merged `macos-audit-26` → `main` and pushed | 3 new commits + the 8 that were stranded, including two Office fixes |
| **v2.0.1, v2.0.0 and v1.0.0 release notes** | every dead link rewritten onto `canvasdownloader.app` and the current org; each replacement verified 200 **before** publishing; v1.0.0 also had a link wrapped in a Google search URL, and v2.0.1 named a Windows asset that is not attached |
| **GitHub Discussions** | enabled |
| The no-JS fix | live and verified: 0 hidden words on `index` and `guide` for a non-JS crawler; JS path byte-identical against the deployed pre-fix site |
| The bundle's `__pycache__` | removed from both specs; a real build now verifies `--deep --strict` exit 0 and boots from sources alone |
| The adoption wording | reverted to **"installs"** per your call, and the rule retired from all five marketing docs so nobody re-argues it |
| Three stale doc claims | the register header (said 19 open, is 7), the proof-strip CSS description, and "the social preview is not set" |

**Not done, deliberately:** the social preview (no API), anything requiring a
signed-in Google/Bing/Partner Center session, and the Windows pass itself.
