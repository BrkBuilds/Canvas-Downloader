<div align="center">

<img src="assets/icon.png" width="120" alt="Canvas Downloader" />

# Canvas Downloader

**Batch-download your entire Canvas LMS course library in minutes.**  
Smart sync, daily auto-sync, Panopto lecture downloads with on-device transcription, and AI-ready file conversion - all in a native desktop app with zero cloud dependency.

[![Version](https://img.shields.io/badge/version-2.0.1-blue?style=flat-square)](https://github.com/birkls/Canvas_LMS_batch_file_downloader/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20(Apple%20Silicon)-lightgrey?style=flat-square)](https://github.com/birkls/Canvas_LMS_batch_file_downloader/releases)
[![Canvas API](https://img.shields.io/badge/Canvas%20LMS-API%20v1-E66000?style=flat-square)](https://canvas.instructure.com/doc/api/)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/Z8Z01ZOY6Q)

[**Website**](https://birkls.github.io/Canvas_LMS_batch_file_downloader/) · [**Microsoft Store**](https://apps.microsoft.com/detail/9n1dwwvrq5wc) · [**Download for Windows / macOS**](https://github.com/birkls/Canvas_LMS_batch_file_downloader/releases/latest) · [**How It Works**](https://birkls.github.io/Canvas_LMS_batch_file_downloader/guide.html)

</div>

---

## What Is This?

Canvas Downloader is a **standalone desktop application** that connects directly to your university's Canvas LMS via the official API and batch-downloads every file from every course - no browser extension, no web scraping, no cloud middleman.

**Keep your course folders up to date automatically.** The sync engine tracks exactly what changed since your last run - new files, updated slides, teacher edits - and only touches what needs updating. Put it on full autopilot with the **Today page**: the app syncs your chosen courses by itself the first time you open it each day and shows you exactly which files arrived.

**Download your Panopto lecture recordings.** The app finds the Panopto recordings linked in your courses and saves them as video (MP4) or audio (MP3) - and can generate **transcripts (.txt) and subtitles (.srt)** with on-device speech recognition. Nothing is ever uploaded anywhere.

**Turn your downloads into AI-ready study material automatically.** One toggle converts every PowerPoint, spreadsheet, video, and code file into a format any AI tool (NotebookLM, ChatGPT, Claude) can read and reason over.

Free, open source, and runs entirely on your machine.

---

## Features

### Core Download Engine

- **Multi-course batch download** - select any combination of courses and pull everything in one shot
- **Canvas module structure preserved** - files land in the same folder hierarchy Canvas uses (or a flat layout, your choice)
- **Async parallel downloads** - `asyncio` + `aiohttp` with configurable concurrency (1-15); Canvas rate-limit backoff built in
- **Atomic file writes** - `.part` staging pattern; a crash mid-download never leaves corrupted files
- **File size filters** - skip large video files you don't need right now. Skipped files are marked as *ignored* in the sync manifest (by design, so future syncs don't keep re-listing them) - restore them anytime from the ignored-files list, even after raising the limit
- **Full Canvas content support** - module files, assignments, syllabi, announcements, discussions, quizzes, and your own submission feedback/grades

### Quick Download - Five Ready-Made Presets

Skip configuration entirely: pick a preset, pick a folder, hit Start.

| Preset | What it does |
|---|---|
| **Complete Canvas Download** | Everything - all files and Canvas content, organized exactly like Canvas, plus full Panopto lecture videos |
| **Daily study pack (Optimized)** | Same as Complete, plus PowerPoint/Word → PDF conversion and Panopto video + audio |
| **100% AI & NotebookLM Ready** | All files in one flat folder, every conversion enabled, Panopto lecture audio in a Recordings folder - drag & drop straight into NotebookLM |
| **Slides & PDFs Only** | Lecture slides and PDF documents, nothing else |
| **Files Only** | Only teacher-uploaded files - no Canvas web content, no recordings |

Or use **Custom Download** for full control over every setting.

### Sync Mode

Keep any Course Folder **permanently in sync** with its Canvas course - one click to pull every new lecture, updated slide deck, and freshly posted file since your last run. The sync engine tracks seven distinct file states:

| State | Description | Default Action |
|---|---|---|
| **New** | Canvas has it, you don't | Download |
| **Update (clean)** | Canvas updated, your copy is untouched | Replace in place |
| **Update (modified)** | Canvas updated, but you edited yours | Keep yours + save new as `_NewVersion` |
| **Deleted locally** | You deleted it, Canvas still has it | Skip (respects intent) |
| **Deleted on Canvas** | Teacher removed it | Info only - never deletes from disk |
| **Up-to-date** | Identical on both sides | Nothing (shown as count badge) |
| **Ignored** | Permanently excluded by you | Always skip |

Change detection uses **MD5 fingerprinting** stored in a per-folder SQLite manifest (`.canvas_sync.db`). Renamed files are resolved with **Levenshtein distance** so a renamed lecture slides file isn't treated as a brand-new download. Panopto recordings participate in sync as first-class citizens: new lectures show up like any other file, and recordings you deleted or ignored stay that way.

Two ways to run it:
- **Quick Sync All** - one click, downloads new files and clean updates, skips everything else automatically
- **Analyze, Review & Sync** - a full per-file diff review across the seven categories with bulk-select tools, extension filters, and per-file ignore/restore

### The Today Page - Sync on Autopilot

A daily dashboard built around one idea: you shouldn't have to think about syncing at all.

- **Daily auto-sync** - pick your courses once, flip a toggle, and the app runs a Quick Sync by itself the first time you open it each day (the "day" rolls over at 4 AM, so late-night sessions don't count as tomorrow)
- **Today's files** - every file downloaded today, grouped per course, with one-click open-file / open-folder actions
- **Quick Sync now** - the same curated set, on demand
- Same safety guarantees as any Quick Sync: never overwrites your edits, never resurrects your deletions

### Panopto Lecture Recordings

Courses that publish lecture recordings through **Panopto** are fully supported - the app discovers every recording linked in your Canvas course (via per-item LTI launches, so even deeply nested folders are found) and fetches them in three clear phases: *discover → download → transcribe*.

Per recording you can save any combination of:

| Output | Format | Setup needed |
|---|---|---|
| **Video** | `.mp4` (stream remux, no re-encode) | None |
| **Audio** | `.mp3` | None |
| **Transcript** | `.txt` | One-time local model download |
| **Subtitles** | `.srt` (timestamped) | One-time local model download |

Transcription runs **100% on your own computer** via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) - choose the model size and spoken language (Danish, English, German, auto-detect, and more). CPU works everywhere; on Windows with an NVIDIA GPU the app can enable CUDA acceleration with a one-click, on-demand library download (~1.3 GB, no admin rights). Each transcription runs in an isolated subprocess, so even a GPU driver crash can't take down the app - it automatically falls back to CPU.

Recordings are sized before download (so disk-space checks include them), can be ignored per-recording, and sync just like regular files.

### AI Optimization - NotebookLM-Ready in One Click

Enable a single toggle and every download is automatically converted into a format Google's NotebookLM (or any AI tool) can ingest directly - no manual reformatting needed:

| Source | Output | Platform | Engine |
|---|---|---|---|
| `.pptx` `.ppt` | `.pdf` | Win + macOS | COM automation / AppleScript |
| `.doc` `.rtf` `.odt` (legacy Word) | `.pdf` (modern `.docx` untouched) | Win + macOS | COM automation / AppleScript |
| `.xlsx` `.xlsm` | `.pdf` + `_Data.txt` (structured AI data) | Win + macOS | openpyxl (data) / COM + AppleScript (PDF) |
| `.xls` (legacy) | `.pdf` only | Win + macOS | COM automation / AppleScript |
| `.mp4` `.mov` `.avi` `.mkv` `.webm` (+15 more) | `.mp3` | Win + macOS | FFmpeg via MoviePy |
| `.html` (Canvas pages) | `.md` / plain text | Win + macOS | BeautifulSoup + markdownify |
| `.zip` `.tar` `.tar.gz` | extracted | Win + macOS | stdlib (zip-bomb protection) |
| 50+ code extensions | `.py.txt` `.js.txt` etc. (extension appended - preserves format hint) | Win + macOS | UTF-8 native |
| External web links | one `.txt` per course | Win + macOS | native |

The Excel data sidecar (`Financials_Data.txt`) is a structured plain-text file containing every sheet's data in CSV format with a cell coordinate grid (A1, B2...) that matches the companion PDF, formula annotations (`250 [Formula: =B2*C2]`), merged cell values repeated across the full merged range, and hidden row/column markers. This lets AI tools cross-reference the visual PDF with precise cell data and understand the underlying formulas - far more useful than PDF parsing alone.

**Note:** The AI data file is generated only for modern Excel formats (`.xlsx`, `.xlsm`). Legacy `.xls` files are converted to PDF only, as the data extraction engine (openpyxl) does not support the binary `.xls` format.

Safety details: archives enforce a **50 GB uncompressed limit** and **100:1 compression-ratio guard**. Video conversion wraps FFmpeg cleanup in a thread-pool with a 10-second timeout to survive corrupt files. Conversions that need Microsoft Office are skipped gracefully (original kept) when Office isn't installed.

### Preset System

Save your exact download configuration - courses, content types, conversion settings, Panopto outputs, output folder - as a named preset. Recall it in one click next time. Presets are stored as plain JSON and can be shared between machines.

### Progress & Monitoring

- Real-time progress dashboard with per-course file counts and MB transferred
- Per-phase Panopto progress (discovery / download / transcription)
- Terminal-style log with color-coded status lines
- Cancel at any time (mid-download, mid-conversion, mid-transcription)
- System notification + completion sound on finish
- **Sync history** - a browsable log of your past sync operations (retention configurable, 10-500 entries)
- Exportable error log for any failed files

---

## Download & Install

No Python installation required. Grab the latest release for your platform:

| Platform | Package | Requirements |
|---|---|---|
| **Windows 10/11** | [Microsoft Store](https://apps.microsoft.com/detail/9n1dwwvrq5wc) (recommended - no SmartScreen warning) or `Canvas_Downloader_Setup_x.y.z.exe` from [Releases](https://github.com/birkls/Canvas_LMS_batch_file_downloader/releases/latest) | Nothing - batteries included |
| **macOS 11+** | `Canvas_Downloader_vx.y.z_macOS.dmg` from [Releases](https://github.com/birkls/Canvas_LMS_batch_file_downloader/releases/latest) | **Apple Silicon only** (M1 or later) - Intel Macs are not supported |

### Windows

1. Install from the **Microsoft Store** (easiest, auto-updates, no warnings), **or** run the `.exe` installer from GitHub Releases
2. If you use the direct installer, Windows SmartScreen will warn you: click **"More info" → "Run anyway"**
3. Launch **Canvas Downloader**

> **Why the SmartScreen warning?** Code-signing certificates cost hundreds of dollars per year. Since this is a free student project, the direct installer is unsigned - the Store build has no warning, and the full source is public here.

### macOS

1. Open the `.dmg` and drag `Canvas Downloader.app` to `/Applications`
2. **First launch:**
   - macOS 13/14: Right-click the app → **Open** → **Open** (Gatekeeper bypass for unsigned apps)
   - macOS 15 (Sequoia) or newer: double-click (it gets blocked), then **System Settings → Privacy & Security**, scroll down, click **Open Anyway**
3. Follow the [interactive Mac setup guide](https://birkls.github.io/Canvas_LMS_batch_file_downloader/mac-setup.html) - it walks through every permission dialog for your exact macOS version

#### What macOS will ask you on first run (this is normal!)

Because the app is free and unsigned, macOS asks for each permission individually. Each prompt appears only once (with one exception, noted below):

| Prompt | Why it appears | What to click |
|---|---|---|
| *"Canvas Downloader" was blocked...* | The app is not signed with a paid Apple certificate | **Open Anyway** (in Privacy & Security settings) |
| *...wants to access key "CanvasDownloader" in your keychain* | Loads/saves your Canvas token securely in the macOS Keychain | **Always Allow** (enter your **Mac login password**, not your Canvas token) |
| *...wants access to files in your Downloads/Documents folder* | Saves your course files where you chose | **OK** / **Allow** |
| *...wants access to control "Microsoft PowerPoint" (or Word / Excel)* | Converts slides and documents to PDF for you | **OK** |
| *...wants to access data from other apps* (macOS 15+ only) | Office → PDF conversions stage files between apps | **Allow** - or grant **Full Disk Access** once to silence it permanently (the app's Settings page shows a status card for this) |

> ⚠️ After **updating** to a new version, macOS treats it as a new app and the Keychain prompt appears once again. Click **Always Allow** - your saved login is intact.

#### Uninstalling (macOS)

1. Log out inside the app (removes your Canvas token from the Keychain)
2. Drag `Canvas Downloader.app` from Applications to the Trash
3. Optional: delete `~/Library/Application Support/CanvasDownloader` (settings & sync pairs)

---

## Quick Start

### 1. Get Your Canvas Access Token

1. Log in to your institution's Canvas → **Account → Settings**
2. Scroll to **Approved Integrations** → **+ New Access Token**
3. Give it a name, no expiry needed, and copy the token

Your token is stored in your OS keyring (Windows Credential Manager / macOS Keychain) - never written to disk in plaintext.

### 2. Download Mode

**First time - Quick Download:**
1. Launch Canvas Downloader and connect with your token + Canvas URL
2. Select your courses, hit **Quick Download**, pick one of the five presets, choose a folder, start
3. Watch the live dashboard; a chime plays when everything is done

**Full control - Custom Download:**
- Configure everything yourself across four cards: file filter & folder structure, Canvas content, AI conversions, and Panopto recordings. Save the configuration as a preset for next time.

### 3. Sync Mode

1. Switch to **Sync Mode** from the sidebar
2. Create a sync pair: pick a Course Folder and link it to a Canvas course (save pairs and multi-course groups in the hub for one-click reuse)
3. **Quick Sync All** for the fast path, or **Analyze, Review & Sync** for the full per-file diff review

### 4. Put It on Autopilot

Open the **Today** page, import your pairs, and enable **daily sync**. From then on, the first app launch of each day fetches everything new automatically and lists today's files per course.

---

## Architecture

Canvas Downloader is ~76 Python modules (~2.9 MB of source) in a deliberately modular structure:

```
start.py                     ← Cross-platform launcher
├── Streamlit server (127.0.0.1, daemonized thread)
└── pywebview window (main thread) - WebView2 on Windows, Cocoa/WKWebView on macOS

app.py                       ← Download mode orchestrator + routing
sync_ui.py                   ← Sync mode orchestrator

ui/                          ← All Streamlit UI components
  auth.py                    ← Sidebar: token auth, navigation, Settings
  course_selector.py         ← Step 1: multi-select with filters
  download_settings.py       ← Step 2: Cards 1-3 (files / content / AI) + Panopto card
  quick_download.py          ← Quick Download presets page
  today_dashboard.py         ← The Today page (daily auto-sync + today's files)
  presets.py                 ← Preset engine + hub modal
  hub_dialog.py              ← Saved Groups & Pairs hub
  sync_dialogs.py            ← Sync pair configuration
  sync_review.py             ← Per-file diff review screen
  sync_confirmation.py       ← Pre-execution confirmation

core/
  state_registry.py          ← Single source of truth for session state keys & defaults
  cancellation.py            ← Global cancel flags + polling
  canvas_logic.py            ← Canvas API wrapper + async download engine
  sync_manager.py            ← SQLite manifest engine (Levenshtein collision resolution)
  preset_manager.py          ← Preset persistence
  auto_sync.py               ← Headless daily Quick-Sync wrapper (Today page)
  today_store.py             ← Today page persistence

engine/
  progress_dashboard.py      ← Shared terminal log + visual dashboard
  post_processing_bridge.py  ← Unified post-processing init (Download + Sync share one pipeline)
  applescript_bridge.py      ← macOS osascript runner (shared by all Office converters)
  notifications.py           ← Native notifications (win11toast / UNUserNotificationCenter)

sync/
  analysis.py                ← Diff engine: Canvas vs local → 7-state categorisation
  execution.py               ← Background async sync execution
  persistence.py             ← Atomic JSON (os.replace + threading.Lock)
  completion.py              ← Post-sync summary + history logging

panopto/                     ← Panopto lecture recording pipeline
  discovery.py               ← LTI 1.3 per-item launches + folder walk
  runner.py                  ← discover → download → transcribe orchestration
  stream.py                  ← MP4/MP3 fetch (FFmpeg remux)
  transcribe.py + transcribe_worker.py ← faster-whisper in an isolated subprocess
  cuda_provision.py          ← On-demand NVIDIA CUDA library download (GPU mode)
  models.py / hardware.py / settings.py / sync_plan.py

converters/                  ← File conversion pipeline
  post_processing.py         ← Unified pipeline runner
  pdf.py / word.py / excel.py            ← Office → PDF/data (Win COM, mac osascript)
  code.py / md.py / url.py / video.py / archive.py

shared/                      ← Cross-cutting UI utilities (helpers, components, theme)
styles/                      ← Static CSS injected via inject_css()
scripts/                     ← Build tooling (Windows build, MSIX packaging, audits)
```

### Notable Engineering Decisions

**Why Streamlit inside a desktop window?**  
Streamlit's reactive model makes complex multi-step wizard UIs fast to build and easy to reason about. `pywebview` wraps it into a proper desktop app on both platforms - a WebView2 window on Windows, a native Cocoa/WKWebView window on macOS - without Electron or a full Qt install.

**Why SQLite for sync state?**  
SQLite in WAL mode gives concurrent-read safety, survives crashes mid-sync, and travels with the folder (`.canvas_sync.db` is hidden alongside the synced files). A plain JSON manifest would need locking at every write and lacks atomic transactions.

**How does cross-platform Office automation work?**  
Windows uses `win32com.client` to drive Word/Excel/PowerPoint as COM servers. macOS uses `osascript` AppleScript via a shared bridge (`engine/applescript_bridge.py`). Both branches implement identical semantics - the calling code never checks the platform. COM instances are self-healing: stale or crashed instances are detected and restarted mid-batch.

**What makes the sync change detection reliable?**  
Files are fingerprinted with MD5 on first download and the hash is stored in SQLite. On subsequent syncs the manifest hash is compared against both the local file and the Canvas file's reported checksum. Levenshtein distance matching handles teacher renames (e.g. `Lecture 3.pdf` → `Lecture 03 - Updated.pdf`) without double-downloading.

**How is transcription kept from destabilising the app?**  
Speech recognition runs in an **isolated subprocess** per recording. A native crash in a GPU driver or inference runtime kills only that worker - the app detects it, downgrades to CPU, and continues the batch. GPU users get CUDA libraries via an on-demand download instead of a 1.3 GB heavier installer for everyone.

**How are Panopto recordings discovered reliably?**  
Generic LTI launches only see the course's root folder. The app performs **per-module-item LTI 1.3 sessionless launches**, so every embedded recording is found - including ones whose embedded IDs have gone stale (they're healed automatically by title matching) - then walks subfolders via Panopto's API.

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI Framework | [Streamlit 1.51](https://streamlit.io) |
| Desktop Window | [pywebview 6.1](https://pywebview.flowrl.com) - WebView2 (Windows) / Cocoa WKWebView (macOS) |
| Canvas API | [canvasapi 3.3](https://canvasapi.readthedocs.io) |
| Async HTTP | [aiohttp 3.11](https://docs.aiohttp.org) + asyncio |
| Async File I/O | [aiofiles 24.1](https://github.com/Tinche/aiofiles) |
| Sync Database | SQLite3 (stdlib) - WAL mode, per-folder manifest |
| Windows Automation | [pywin32 308](https://github.com/mhammond/pywin32) - COM interface to Office |
| macOS Automation | `osascript` AppleScript - feature-parity with COM |
| Speech Recognition | [faster-whisper 1.2](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) - CPU everywhere, optional NVIDIA CUDA |
| Video Processing | [MoviePy 2.2](https://zulko.github.io/moviepy/) + FFmpeg via imageio-ffmpeg |
| HTML → Markdown | [BeautifulSoup4 4.12](https://www.crummy.com/software/BeautifulSoup/) + [markdownify 0.14](https://github.com/matthewwithanm/python-markdownify) |
| Excel Data Extraction | [openpyxl 3.1](https://openpyxl.readthedocs.io) |
| Credential Storage | [keyring 25.6](https://github.com/jaraco/keyring) - OS Keychain / Credential Manager |
| Notifications | win11toast (Windows) · UNUserNotificationCenter via pyobjc (macOS) |
| Packaging | [PyInstaller](https://pyinstaller.org) + Inno Setup (Windows installer) + MSIX (Microsoft Store) |

---

## Building from Source

Requires Python 3.11+ and the dependencies in `requirements.txt`.

```bash
# Clone
git clone https://github.com/birkls/Canvas_LMS_batch_file_downloader.git
cd Canvas_LMS_batch_file_downloader

# Install dependencies
pip install -r requirements.txt

# Run from source
python start.py
```

### Packaging

**Windows** (produces the Inno Setup installer):
```bash
python scripts/build_windows.py        # version_info → PyInstaller → Inno Setup
# or manually: pyinstaller Canvas_Downloader.spec, then compile Canvas_Downloader_Setup.iss
```

**Microsoft Store** (MSIX):
```bash
python scripts/build_msix.py
```

**macOS** (produces `Canvas Downloader.app`, Apple Silicon):
```bash
pyinstaller --clean Canvas_Downloader_macOS.spec
codesign --force --deep -s - --entitlements entitlements.mac.plist "Canvas Downloader.app"
```

The macOS spec includes the `com.apple.security.automation.apple-events` entitlement so AppleScript Office automation works, and both specs apply a WebKit compatibility patch to Streamlit for older Safari engines.

---

## Security Notes

- Your Canvas Access Token is stored in your OS keyring (Windows Credential Manager / macOS Keychain). On Windows, if the keyring is unavailable, an encrypted DPAPI fallback file is used - the ciphertext is bound to your Windows user account and unreadable by anyone else. macOS deliberately has no disk fallback
- The Streamlit server binds to `127.0.0.1` only - zero network exposure beyond your own machine. Note for **shared computers** (e.g. lab PCs with multiple users logged in at once): localhost ports are reachable by other local users on the same machine, and the app auto-signs-in from your keyring - prefer running it on your personal device
- The app talks to exactly two kinds of servers: your university's Canvas, and (only if you enable lecture downloads) your university's Panopto. Optional one-time downloads: transcription models from Hugging Face, CUDA libraries from NVIDIA. There is no backend, no analytics, no telemetry
- Lecture transcription is **fully local** - audio never leaves your machine
- Archive extraction enforces a 50 GB / 100:1 ratio hard limit against zip bombs
- All Canvas data rendered into HTML is passed through `html.escape()` before injection
- Debug logs redact Bearer tokens and signed download-URL tokens (`verifier=`) before anything is written to disk

---

## Contributing

Issues and PRs are welcome. If you find a bug or want to request a feature, open an issue on GitHub.

When contributing code, follow the CSS/UI rules in `CLAUDE.md` - they exist because we learned the hard way.

---

## License

MIT - see [LICENSE](LICENSE) for details.

---

<div align="center">
<sub>Built with Python, Streamlit, and an unreasonable amount of CSS debugging.</sub>
</div>
