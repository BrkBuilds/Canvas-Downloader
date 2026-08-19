<div align="center">

<img src="assets/icon.png" width="112" alt="Canvas Downloader app icon" />

# Canvas Downloader

### Download all your Canvas files at once - then keep the folder in sync, automatically.

A free, open source desktop app for **Canvas LMS**. Batch-download every file from every course,
keep your folders up to date by itself, save **Panopto** lecture recordings with on-device
transcription, and convert everything into AI-ready study material. Windows and macOS. No cloud, no
account, no telemetry.

[![Latest release](https://img.shields.io/github/v/release/BrkBuilds/Canvas-Downloader?style=flat-square&color=2563eb&label=release)](https://github.com/BrkBuilds/Canvas-Downloader/releases/latest)
[![GitHub downloads](https://img.shields.io/github/downloads/BrkBuilds/Canvas-Downloader/total?style=flat-square&color=16a34a&label=GitHub%20downloads)](https://github.com/BrkBuilds/Canvas-Downloader/releases)
[![Microsoft Store](https://img.shields.io/badge/Microsoft%20Store-install-0078D4?style=flat-square&logo=microsoftstore&logoColor=white)](https://apps.microsoft.com/detail/9n1dwwvrq5wc)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-lightgrey?style=flat-square)](#download)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

**[Download](#download)** · **[Website](https://canvasdownloader.app/)** · **[How it works](https://canvasdownloader.app/guide.html)** · **[Mac setup guide](https://canvasdownloader.app/mac-setup.html)** · **[FAQ](#faq)**

</div>

---

## Contents

- [What it does](#what-it-does)
- [Download](#download)
- [Screenshots](#screenshots)
- [Features](#features)
- [How it compares](#how-it-compares)
- [Quick start](#quick-start)
- [FAQ](#faq)
- [Privacy and security](#privacy-and-security)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Building from source](#building-from-source)
- [Contributing](#contributing)
- [Disclaimer and acceptable use](#disclaimer-and-acceptable-use)

---

## What it does

Canvas Downloader is a **standalone desktop application** that connects to your university's Canvas
LMS through the official Canvas API and downloads every file from every course you select. No
browser extension, no web scraping, no cloud middleman, no account to create. It signs in as you,
with your own Canvas access token, and runs entirely on your own machine.

Four things it does that a manual download cannot:

**Batch download entire courses.** Select any combination of courses and pull everything in one run
- module files, assignments, syllabi, announcements, discussions, quizzes and your own submission
feedback. Files land in the same folder structure Canvas uses, or flat, whichever you pick.

**Keep folders up to date by itself.** The sync engine tracks exactly what changed since your last
run - new files, updated slide decks, teacher edits - and touches only what needs updating. It never
overwrites a file you edited and never resurrects a file you deleted. Turn on the **Today page** and
it syncs your chosen courses on its own the first time you open the app each day.

**Save Panopto lecture recordings.** The app finds the Panopto recordings linked in your courses and
saves them as video or audio, and can generate **transcripts and subtitles** with speech recognition
that runs on your own computer. Nothing is uploaded anywhere. Please read the
[disclaimer](DISCLAIMER.md) before enabling lecture downloads.

**Turn downloads into AI-ready study material.** One toggle converts every PowerPoint, Word
document, spreadsheet, video, web page and code file into a format NotebookLM, ChatGPT or Claude can
read and reason over.

---

## Download

No Python installation required. Everything is bundled.

| Platform | Get it | Requirements |
|---|---|---|
| **Windows 10/11** | **[Microsoft Store](https://apps.microsoft.com/detail/9n1dwwvrq5wc)** (recommended - auto-updates, no security warning)<br>or the `.exe` installer from **[Releases](https://github.com/BrkBuilds/Canvas-Downloader/releases/latest)** | Nothing, batteries included |
| **macOS 11+** | `Canvas_Downloader_macOS.dmg` from **[Releases](https://github.com/BrkBuilds/Canvas-Downloader/releases/latest)** | **Apple Silicon only** (M1 or later). Intel Macs are not supported |

### Windows

1. Install from the **Microsoft Store**, or run the `.exe` installer from Releases.
2. If you used the direct installer, Windows SmartScreen will warn you. Click **More info**, then
   **Run anyway**.
3. Launch **Canvas Downloader**.

> **Why the SmartScreen warning?** Code-signing certificates cost hundreds of dollars per year. This
> is a free student project, so the direct installer is unsigned. The Microsoft Store build has no
> warning, and the full source is public in this repository.

### macOS

1. Open the `.dmg` and drag **Canvas Downloader** to your Applications folder.
2. First launch:
   - **macOS 13 and 14:** right-click the app, choose **Open**, then **Open** again.
   - **macOS 15 (Sequoia) and newer:** double-click it, let it get blocked, then go to
     **System Settings → Privacy & Security**, scroll down and click **Open Anyway**. Sequoia removed
     the old right-click bypass, so this is the only route.
3. Follow the **[interactive Mac setup guide](https://canvasdownloader.app/mac-setup.html)**. It walks
   through every permission dialog for your exact macOS version.

<details>
<summary><b>What macOS will ask you on first run (this is normal)</b></summary>

<br>

Because the app is free and unsigned, macOS asks for each permission separately. Each prompt appears
once, with one exception noted below.

| Prompt | Why it appears | What to click |
|---|---|---|
| *"Canvas Downloader" was blocked* | The app is not signed with a paid Apple certificate | **Open Anyway**, in Privacy & Security |
| *wants to access key "CanvasDownloader" in your keychain* | Saves your Canvas token securely in the macOS Keychain | **Always Allow**, then enter your **Mac login password** (not your Canvas token) |
| *wants access to files in your Downloads/Documents folder* | Saves your course files where you chose | **OK** or **Allow** |
| *wants access to control "Microsoft PowerPoint"* (or Word, Excel) | Converts slides and documents to PDF for you | **OK** |
| *wants to access data from other apps* (macOS 15+) | Office to PDF conversion stages files between apps | **Allow**, or grant **Full Disk Access** once to silence it permanently. The app's Settings page has a status card for this |

After **updating** to a new version, macOS treats it as a new app and the Keychain prompt appears
once more. Click **Always Allow**. Your saved login is intact.

**Uninstalling:** log out inside the app first (this removes your token from the Keychain), drag the
app to the Trash, and optionally delete `~/Library/Application Support/CanvasDownloader`.

</details>

---

## Screenshots

<table>
  <tr>
    <td width="50%" valign="top"><img src="docs/assets/screenshots/institution-picker.png" alt="The Canvas Downloader login screen with the institution directory open and a search typed" /><br><sub><b>Find your school.</b> 4,757 Canvas institutions, searchable - no need to know your URL.</sub></td>
    <td width="50%" valign="top"><img src="docs/assets/screenshots/progress.png" alt="The live download dashboard showing transferred bytes, speed, file count, time remaining and a running log" /><br><sub><b>Watch it run.</b> Live speed, ETA, and a log of every file.</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/assets/screenshots/course-selection.png" alt="The Canvas Downloader course list with several courses selected and a search filter applied" /><br><sub><b>Pick your courses.</b> Search, filter and select as many as you like.</sub></td>
    <td width="50%" valign="top"><img src="docs/assets/screenshots/quick-download.png" alt="The five Quick Download presets in Canvas Downloader" /><br><sub><b>Quick Download.</b> Five ready-made presets, one click.</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/assets/screenshots/custom-download.png" alt="The Custom Download configuration screen: course files, Canvas content, AI conversions and Panopto recordings" /><br><sub><b>Or configure everything.</b> Files, Canvas content, AI conversions, Panopto recordings.</sub></td>
    <td width="50%" valign="top"><img src="docs/assets/screenshots/sync-review.png" alt="The sync review screen showing new, updated, locally edited and locally deleted files with per-file checkboxes" /><br><sub><b>Review every change.</b> New, updated, edited locally, deleted - you decide, file by file.</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/assets/screenshots/Sync-frontpage.png" alt="The sync page listing local course folders linked to Canvas courses" /><br><sub><b>Link folders to courses.</b> Then keep them current without downloading it all again.</sub></td>
    <td width="50%" valign="top"><img src="docs/assets/screenshots/today-page.png" alt="The Today page with the daily auto-sync switched on and the courses it covers" /><br><sub><b>Today.</b> Flip one toggle and your courses sync themselves each morning.</sub></td>
  </tr>
</table>

> Short demo clips for each mode are on the **[website](https://canvasdownloader.app/)**.

---

## Features

### Batch download engine

- **Multi-course batch download** - select any combination of courses and pull everything in one run
- **Canvas structure preserved** - files land in the same folder hierarchy Canvas uses, or flat
- **Parallel downloads** - `asyncio` and `aiohttp` with configurable concurrency (1 to 15), with
  Canvas rate-limit backoff built in
- **Atomic writes** - `.part` staging, so a crash mid-download never leaves a corrupted file
- **File size filters** - skip the large videos you do not need right now. Skipped files are marked
  *ignored* in the sync manifest so future runs stop listing them, and you can restore them at any
  time from the ignored-files list
- **Full Canvas content** - module files, assignments, syllabi, announcements, discussions, quizzes,
  and your own submission feedback and grades

### Quick Download - five ready-made presets

Skip configuration entirely. Pick a preset, pick a folder, press Start.

| Preset | What it does |
|---|---|
| **Complete Canvas Download** | Everything. All files and Canvas content, organised exactly like Canvas, plus full Panopto lecture videos |
| **Daily study pack** | Same as Complete, plus PowerPoint and Word to PDF conversion, and Panopto video and audio |
| **100% AI and NotebookLM ready** | Every file in one flat folder, every conversion enabled, lecture audio in a Recordings folder. Drag straight into NotebookLM |
| **Slides and PDFs only** | Lecture slides and PDF documents, nothing else |
| **Files only** | Only teacher-uploaded files. No Canvas web content, no recordings |

Or use **Custom Download** for control over every individual setting.

### Sync mode

Keep any folder **permanently in sync** with its Canvas course. One click pulls every new lecture,
updated slide deck and freshly posted file since your last run. The engine tracks seven distinct
file states:

| State | What it means | Default action |
|---|---|---|
| **New** | Canvas has it, you do not | Download |
| **Update (clean)** | Canvas updated it, your copy is untouched | Replace in place |
| **Update (modified)** | Canvas updated it, but you edited yours | Keep yours, save the new one as `_NewVersion` |
| **Deleted locally** | You deleted it, Canvas still has it | Skip, your intent is respected |
| **Deleted on Canvas** | The teacher removed it | Shown for information only. Never deletes from your disk |
| **Up to date** | Identical on both sides | Nothing, shown as a count |
| **Ignored** | Permanently excluded by you | Always skip |

Change detection uses **MD5 fingerprinting** stored in a per-folder SQLite manifest
(`.canvas_sync.db`, hidden alongside your files). Renamed files are matched with **Levenshtein
distance**, so a lecturer renaming `Lecture 3.pdf` to `Lecture 03 - Updated.pdf` is recognised as
the same file instead of downloading a second copy. Panopto recordings take part in sync as
first-class files.

Two ways to run it:

- **Quick Sync** - one click. Downloads new files and clean updates, skips everything else.
- **Analyze, Review & Sync** - a full per-file diff across all seven states, with bulk selection,
  extension filters and per-file ignore or restore.

### The Today page - sync on autopilot

A daily dashboard built around one idea: you should not have to think about syncing at all.

- **Daily auto-sync** - pick your courses once, flip a toggle, and the app runs a Quick Sync by
  itself the first time you open it each day. The day rolls over at 4 AM, so a late-night session
  does not count as tomorrow
- **Today's files** - everything that arrived today, grouped per course, with one-click open file
  and open folder
- **Quick Sync now** - the same curated set, on demand
- Same guarantees as any sync: never overwrites your edits, never resurrects your deletions

### Panopto lecture recordings

Courses that publish recordings through **Panopto** are fully supported. The app discovers every
recording linked in your Canvas course using per-item LTI launches, so even deeply nested folders
are found, then works in three clear phases: **discover, download, transcribe**.

Per recording you can save any combination of:

| Output | Format | Setup needed |
|---|---|---|
| **Shortcut** | `.url` (Windows) / `.webloc` (macOS) - opens the lecture on Panopto | None |
| **Video** | `.mp4`, stream remux with no re-encode | None |
| **Audio** | `.mp3` | None |
| **Transcript** | `.txt` | One-time local model download |
| **Subtitles** | `.srt`, timestamped | One-time local model download |

The **Shortcut** output costs no bandwidth, no disk space and no time, and it answers what a
transcript cannot: take me back to the lecture, with the slides, the screen capture and Panopto's
own search still attached. It is a pointer, so it stops working when your Canvas access ends, which
is exactly when people want the offline copy - treat it as a companion to a download, not a
replacement.

Transcription runs **entirely on your own computer** through
[faster-whisper](https://github.com/SYSTRAN/faster-whisper). Choose the model size and the spoken
language (Danish, English, German, auto-detect and more). CPU works everywhere. On Windows with an
NVIDIA GPU the app can enable CUDA acceleration through a one-click download of about 1.3 GB, with
no admin rights needed. Each transcription runs in an isolated subprocess, so even a GPU driver
crash cannot take down the app - it falls back to CPU and carries on.

Recordings are sized before download so disk-space checks include them, can be ignored individually,
and sync like any other file. Panopto support can be switched **off completely** in Settings: no
institution lookup, no discovery, no acceptable-use dialog and no recordings in any download or
sync.

### AI optimization - NotebookLM ready in one click

Enable one toggle and every download is converted into a format an AI tool can ingest directly.

| Source | Output | Engine |
|---|---|---|
| `.pptx` `.ppt` | `.pdf` | COM automation (Windows) / AppleScript (macOS) |
| `.doc` `.rtf` `.odt` legacy Word | `.pdf`, modern `.docx` untouched | COM automation / AppleScript |
| `.xlsx` `.xlsm` | `.pdf` plus `_Data.txt` structured data | openpyxl for data, COM or AppleScript for PDF |
| `.xls` legacy | `.pdf` only | COM automation / AppleScript |
| `.mp4` `.mov` `.avi` `.mkv` `.webm` and 15 more | `.mp3` | FFmpeg through MoviePy |
| `.html` Canvas pages | `.md` or plain text | BeautifulSoup and markdownify |
| `.zip` `.tar` `.tar.gz` | extracted | Python stdlib, with zip-bomb protection |
| 50+ code extensions | `.py.txt`, `.js.txt` and so on | UTF-8 native |
| External web links | one `.txt` per course | native |

The Excel data sidecar is worth calling out. `Financials_Data.txt` contains every sheet in CSV form
with a cell coordinate grid (A1, B2 and so on) matching the companion PDF, formula annotations such
as `250 [Formula: =B2*C2]`, merged cell values repeated across the full merged range, and hidden row
and column markers. An AI tool can cross-reference the visual PDF against precise cell data and
understand the formulas underneath, which is far more useful than parsing the PDF alone.

**Note:** the data sidecar is generated for modern Excel formats only (`.xlsx`, `.xlsm`). Legacy
`.xls` files are converted to PDF only, because the extraction engine (openpyxl) does not read the
binary `.xls` format.

Safety details: archives enforce a **50 GB uncompressed limit** and a **100:1 compression ratio
guard**. Every converter that deletes the file it converted from verifies the output is real first -
present, non-empty and structurally valid - so a failed conversion can never destroy your only copy.
Conversions that need Microsoft Office are skipped gracefully, keeping the original, when Office is
not installed.

### Signing in

A searchable directory of **4,757 verified Canvas institutions** sits next to the URL field on the
login screen. Find your university, and its Canvas address fills itself in. The field stays fully
editable, so this is a shortcut and never a gate - every Canvas school works whether or not it is
listed, and the picker opens on the institutions in your own country.

Your access token is stored in your operating system's keyring (Windows Credential Manager, macOS
Keychain) and never written to disk in plain text.

### Presets, progress and history

- **Presets** - save a complete configuration (courses, content types, conversions, Panopto outputs,
  output folder) under a name and recall it in one click. Stored as plain JSON, so they move between
  machines
- **Live dashboard** - per-course file counts, MB transferred, transfer speed and a time-remaining
  estimate that learns as the run goes
- **Per-phase Panopto progress** - discovery, download and transcription reported separately
- **Terminal-style log** with colour-coded status lines
- **Cancel at any point** - mid-download, mid-conversion or mid-transcription
- **System notification and a chime** when a run finishes
- **Sync history** - a browsable log of past runs, retention configurable from 10 to 500 entries
- **Exportable error log** for any file that failed

---

## How it compares

| | Canvas Downloader | Browser extension | Downloading by hand |
|---|---|---|---|
| Whole course in one action | Yes | Usually per page | No |
| Keeps folders in sync later | Yes, and automatically | No | No |
| Panopto lecture recordings | Yes, with transcripts | Rarely | No |
| Converts to AI-ready formats | Yes | No | No |
| Needs your Canvas password | No, an access token you create and can revoke | Often reads your live session | n/a |
| Where your files and token go | Only your computer | Varies by extension | Your computer |
| Works after the semester ends | Yes, you keep the files | n/a | Yes |
| Cost | Free and open source | Varies | Free, but slow |

---

## Quick start

### 1. Get your Canvas access token

1. Log in to your institution's Canvas, then go to **Account → Settings**.
2. Scroll to **Approved Integrations** and click **+ New Access Token**.
3. Give it a name. No expiry date is needed. Copy the token.

You can revoke it from the same page at any time.

### 2. Download your courses

**First time, the fast path:**

1. Launch Canvas Downloader, find your university in the institution picker, and paste your token.
2. Select your courses, press **Quick Download**, pick one of the five presets and choose a folder.
3. Watch the live dashboard. A chime plays when it is done.

**Full control:** use **Custom Download** to configure everything yourself across four cards - file
filter and folder structure, Canvas content, AI conversions and Panopto recordings. Save it as a
preset for next time.

### 3. Keep it up to date

1. Switch to **Sync Mode** in the sidebar.
2. Create a sync pair: pick a folder and link it to a Canvas course. Save pairs and multi-course
   groups in the hub for one-click reuse.
3. Use **Quick Sync** for the fast path, or **Analyze, Review & Sync** for the full per-file review.

### 4. Put it on autopilot

Open the **Today** page, import your pairs and turn on daily sync. From then on, the first launch of
each day fetches everything new and lists today's files per course.

---

## FAQ

<details>
<summary><b>Is this allowed? Will my university know?</b></summary>

The app uses the official Canvas API with an access token you create yourself, which is a documented
and supported Canvas feature. It can only reach material your own account is already permitted to
open, and it downloads the same files you could save one by one from your browser.

Canvas does log API activity the same way it logs normal use. Nothing is hidden from your
institution, and nothing pretends to be a different user.

Lecture recordings are a separate question, so please read the next answer and the
[full disclaimer](DISCLAIMER.md).

</details>

<details>
<summary><b>What about Panopto lecture recordings specifically?</b></summary>

Panopto has a download button your institution can switch on or off for each recording. **This app
does not read that setting**, so saving a recording may still be against your institution's rules
even when the app succeeds.

Recordings belong to your lecturer and your institution. Keep them for your own study, and never
share or republish them. Panopto support is off by default and can be switched off entirely in
Settings.

</details>

<details>
<summary><b>Is my Canvas token safe?</b></summary>

It is stored in your operating system's credential store - Windows Credential Manager or the macOS
Keychain - and never written to disk in plain text. On Windows, if the keyring is unavailable, an
encrypted DPAPI fallback file is used, whose ciphertext is bound to your Windows user account.
macOS deliberately has no disk fallback.

The app has no backend and no accounts. Your token never leaves your machine except to talk to your
own university's Canvas. You can revoke it from Canvas at any time.

</details>

<details>
<summary><b>Does it work with my university?</b></summary>

If your university uses Canvas, yes. The app talks to the standard Canvas API, not to anything
institution-specific. The login screen lists 4,757 verified Canvas institutions to save you typing
the address, but that list is only a convenience - schools not on it work exactly the same way once
you paste your Canvas URL.

</details>

<details>
<summary><b>Will it overwrite work I have edited?</b></summary>

No. If Canvas has a newer version of a file you have edited locally, your copy is kept and the new
version is saved alongside it with a `_NewVersion` suffix. The same protection covers files the app
converted for you, such as a PDF made from a slide deck.

Files you deleted on purpose are not downloaded again, and files removed from Canvas are never
deleted from your disk.

</details>

<details>
<summary><b>Do I need Python or any other install?</b></summary>

No. The Windows and macOS builds bundle everything, including FFmpeg. Python is only needed if you
want to run from source.

</details>

<details>
<summary><b>Why does Windows or macOS warn me about the app?</b></summary>

Code-signing certificates cost hundreds of dollars a year and this is a free project, so the direct
downloads are unsigned. The **Microsoft Store** build is signed and shows no warning. On macOS,
follow the [setup guide](https://canvasdownloader.app/mac-setup.html) for your version. All the
source is in this repository if you would rather build it yourself.

</details>

<details>
<summary><b>Does transcription send my lectures to a server?</b></summary>

No. Speech recognition runs on your own computer through faster-whisper. The only thing downloaded
is the model itself, once, from Hugging Face. Audio never leaves your machine.

</details>

<details>
<summary><b>Does it work on an Intel Mac?</b></summary>

No. The macOS build is Apple Silicon only (M1 or later). Running from source on an Intel Mac may
work but is not tested or supported.

</details>

<details>
<summary><b>Can I use it on a shared or lab computer?</b></summary>

It is better not to. The app signs in automatically from your keyring, and a local server on
`127.0.0.1` is reachable by other users signed in to the same machine at the same time. Prefer your
own device.

</details>

---

## Privacy and security

- **No backend, no accounts, no analytics, no telemetry.** There is no server to send anything to.
- The app talks to exactly two kinds of servers: **your university's Canvas**, and, only if you turn
  on lecture downloads, **your university's Panopto**. The only other network calls are optional
  one-time downloads - a transcription model from Hugging Face, CUDA libraries from NVIDIA, and a
  version check against this repository's releases.
- Your **access token** lives in the OS keyring. See the FAQ above for the details.
- The local Streamlit server binds to **`127.0.0.1` only**, so nothing is exposed to your network.
  On a shared computer, other users signed in at the same time can reach localhost ports, so prefer
  a personal device.
- **Transcription is fully local.** Audio never leaves your machine.
- Archive extraction enforces a **50 GB uncompressed limit** and a **100:1 ratio guard** against zip
  bombs, and refuses any archive member that would escape the target folder.
- All Canvas data rendered into the UI is escaped before injection.
- Debug logs **redact** Bearer tokens and signed download-URL tokens before anything is written to
  disk.

---

## Architecture

Canvas Downloader is 81 Python modules (about 4.3 MB of source) covered by **3,827 tests**, in a
deliberately modular structure.

```text
start.py                     Cross-platform launcher
├── Streamlit server (127.0.0.1, daemonized thread)
└── pywebview window (main thread), WebView2 on Windows, Cocoa/WKWebView on macOS

app.py                       Download mode orchestrator and routing
sync_ui.py                   Sync mode orchestrator

ui/                          Streamlit UI components
  auth.py                    Sidebar: token auth, navigation, Settings
  institution_picker.py      Searchable directory of 4,757 Canvas institutions
  course_selector.py         Step 1: multi-select with search and filters
  download_settings.py       Step 2: file, content, AI and Panopto cards
  quick_download.py          Quick Download presets page
  today_dashboard.py         The Today page (daily auto-sync and today's files)
  presets.py                 Preset engine and hub modal
  hub_dialog.py              Saved Groups & Pairs hub
  sync_dialogs.py            Sync pair configuration
  sync_review.py             Per-file diff review screen
  sync_confirmation.py       Pre-execution confirmation
  panopto_page.py            Transcription model and GPU management
  update_banner.py           New-release notice

core/
  library.py                 The unified store: saved pairs, groups, daily membership
  library_migrate.py         One-time reversible migration of the legacy pair files
  pair_labels.py             Your own name for a (course, folder) link
  course_cache.py            Course list served from cache, refreshed off the render path
  state_registry.py          Single source of truth for session state keys and defaults
  cancellation.py            Global cancel flags and polling
  canvas_logic.py            Canvas API wrapper and async download engine
  sync_manager.py            SQLite manifest engine (Levenshtein collision resolution)
  preset_manager.py          Preset persistence
  auto_sync.py               Headless daily Quick Sync wrapper (Today page)
  today_store.py             Today page settings
  health_log.py              Session health record and orphan-process reaping

engine/
  progress_dashboard.py      Shared terminal log and visual dashboard
  estimation.py              Time-remaining model, one estimator for every phase
  post_processing_bridge.py  Unified post-processing init (download and sync share it)
  applescript_bridge.py      macOS osascript runner, shared by all Office converters
  notifications.py           Native notifications

sync/
  analysis.py                Diff engine: Canvas vs local, seven-state categorisation
  execution.py               Background async sync execution
  persistence.py             Atomic JSON (os.replace plus a lock)
  completion.py              Post-sync summary and history logging

panopto/                     Lecture recording pipeline
  discovery.py               Per-item LTI launches and folder walk
  runner.py                  discover, download, transcribe orchestration
  stream.py                  MP4/MP3 fetch (FFmpeg remux)
  shortcut.py                .url / .webloc link output
  transcribe.py              faster-whisper in an isolated subprocess
  transcribe_worker.py       The isolated worker process
  cuda_provision.py          On-demand NVIDIA CUDA library download
  models.py, hardware.py, settings.py, sync_plan.py, auth.py, institution.py

converters/                  File conversion pipeline
  post_processing.py         Unified pipeline runner
  verify.py                  Output gates: a source is deleted only if the product is real
  pdf.py, word.py, excel.py  Office to PDF and data
  code.py, md.py, url.py, video.py, archive.py

shared/                      Cross-cutting utilities
  helpers.py, components.py, theme.py, legal.py
  institutions.py            Generated verified Canvas institution list
  shortcuts.py               .url / .webloc format, shared by three consumers

styles/                      Static CSS injected via inject_css()
scripts/                     Build and maintenance tooling, not bundled in the app
tests/                       3,827 tests
```

### Notable engineering decisions

**Why Streamlit inside a desktop window?** Streamlit's reactive model makes a multi-step wizard UI
fast to build and easy to reason about. `pywebview` wraps it into a real desktop app on both
platforms, a WebView2 window on Windows and a native Cocoa/WKWebView window on macOS, with no
Electron and no Qt install.

**Why SQLite for sync state?** WAL mode gives concurrent-read safety, survives a crash mid-sync, and
the manifest travels with the folder. A JSON manifest would need locking on every write and has no
atomic transactions.

**How does cross-platform Office automation work?** Windows drives Word, Excel and PowerPoint as COM
servers through `win32com.client`. macOS uses AppleScript through a shared bridge. Both branches
implement identical semantics, so the calling code never checks the platform. COM instances are
self-healing: a stale or crashed instance is detected and restarted mid-batch, and on macOS the app
only quits an Office app it launched itself, so it can never close a document you were working on.

**What makes change detection reliable?** Files are fingerprinted with MD5 on first download and the
hash is stored in SQLite. Later syncs compare that hash against both the local file and the checksum
Canvas reports. Levenshtein matching handles teacher renames without downloading a second copy.

**How is transcription kept from destabilising the app?** Speech recognition runs in an isolated
subprocess per recording. A native crash in a GPU driver or inference runtime kills only that
worker. The app notices, downgrades to CPU and continues the batch. GPU users fetch CUDA libraries
on demand rather than everyone carrying a 1.3 GB heavier installer.

**How are Panopto recordings discovered reliably?** A generic LTI launch only sees the course's root
folder. The app performs per-module-item LTI 1.3 sessionless launches, so every embedded recording
is found, including ones whose embedded IDs have gone stale, which are healed by title matching.
Subfolders are then walked through Panopto's API with explicit depth and count bounds.

---

## Tech stack

| Layer | Technology |
|---|---|
| UI framework | [Streamlit 1.51](https://streamlit.io) |
| Desktop window | [pywebview 6.1](https://pywebview.flowrl.com), WebView2 on Windows, Cocoa WKWebView on macOS |
| Canvas API | [canvasapi 3.3](https://canvasapi.readthedocs.io) |
| Async HTTP | [aiohttp 3.11](https://docs.aiohttp.org) with asyncio |
| Async file I/O | [aiofiles 24.1](https://github.com/Tinche/aiofiles) |
| Sync database | SQLite3 (stdlib), WAL mode, one manifest per folder |
| Windows automation | [pywin32 308](https://github.com/mhammond/pywin32), COM interface to Office |
| macOS automation | `osascript` AppleScript, feature parity with COM |
| Speech recognition | [faster-whisper 1.2](https://github.com/SYSTRAN/faster-whisper) on CTranslate2, CPU everywhere, optional NVIDIA CUDA |
| Video processing | [MoviePy 2.2](https://zulko.github.io/moviepy/) with FFmpeg via imageio-ffmpeg |
| HTML to Markdown | [BeautifulSoup4 4.12](https://www.crummy.com/software/BeautifulSoup/) and [markdownify 0.14](https://github.com/matthewwithanm/python-markdownify) |
| Excel extraction | [openpyxl 3.1](https://openpyxl.readthedocs.io) |
| Credential storage | [keyring 25.6](https://github.com/jaraco/keyring) |
| Notifications | win11toast on Windows, UNUserNotificationCenter via pyobjc on macOS |
| Packaging | [PyInstaller](https://pyinstaller.org), Inno Setup for the Windows installer, MSIX for the Microsoft Store |

---

## Building from source

Requires Python 3.11 or newer.

```bash
git clone https://github.com/BrkBuilds/Canvas-Downloader.git
cd Canvas-Downloader

pip install -r requirements.txt

python start.py
```

Run the test suite:

```bash
python -m pytest
```

### Packaging

**Windows**, produces the Inno Setup installer:

```bash
python scripts/build_windows.py     # version_info, then PyInstaller, then Inno Setup
```

**Microsoft Store** (MSIX):

```bash
python scripts/build_msix.py
```

**macOS**, produces `Canvas Downloader.app` for Apple Silicon:

```bash
pyinstaller --clean Canvas_Downloader_macOS.spec
codesign --force --deep -s - --entitlements entitlements.mac.plist "Canvas Downloader.app"
```

The macOS spec includes the `com.apple.security.automation.apple-events` entitlement so AppleScript
Office automation works. Both specs apply a WebKit compatibility patch to Streamlit for older Safari
engines and inject the startup splash so the window is never blank.

---

## Contributing

Issues and pull requests are welcome. See **[CONTRIBUTING.md](CONTRIBUTING.md)** for how to set up a
development environment, what the test and audit workflow looks like, and the UI rules to follow.

If you found a security issue, please read **[SECURITY.md](SECURITY.md)** first rather than opening a
public issue.

`CLAUDE.md` in the repository root is the engineering logbook. It is long, and deliberately so -
every entry records a real failure, the measurement that found it and why the obvious fix was wrong.
Read the section relevant to whatever you are touching before you touch it.

---

## Disclaimer and acceptable use

Canvas Downloader saves a local copy of course material you already have access to. It signs in as
**you**, with **your** own Canvas access token, and can only reach what your account is already
permitted to open. It contains no decryption and breaks no copy protection. When Canvas or Panopto
refuses a request, the app reports the refusal and moves on.

**Lecture recordings:** Panopto has a download button your institution can switch on or off per
recording. **This app does not read that setting**, so saving a recording may still be against your
institution's rules. Recordings belong to your lecturer and your institution. Keep them for your own
study, and never share or republish them.

You are responsible for how you use this software, including compliance with your institution's IT
regulations, any applicable terms of service, and your local copyright law.

Full text: **[DISCLAIMER.md](DISCLAIMER.md)**. If you represent an institution or a rights holder and
have a concern, please open an issue or email **brkbuilds1@gmail.com** first. It will be addressed
promptly.

---

## License

MIT. See [LICENSE](LICENSE).

---

<div align="center">

**[Download](https://github.com/BrkBuilds/Canvas-Downloader/releases/latest)** · **[Website](https://canvasdownloader.app/)** · **[Microsoft Store](https://apps.microsoft.com/detail/9n1dwwvrq5wc)**

If this saved you an afternoon of clicking, a star costs nothing and helps other students find it.

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/Z8Z01ZOY6Q)

<sub>Built with Python, Streamlit, and an unreasonable amount of CSS debugging.</sub>

</div>
