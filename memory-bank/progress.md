# Progress: Canvas Downloader

## Completed Milestones
- [x] **Project Initialization**: Repository setup and initial architecture.
- [x] **Core Downloader**: Bulk downloading of course files/modules.
- [x] **Smart Sync Feature**:
    - [x] `SyncManager` class implementation and SQLite migration.
    - [x] UI for folder-course pairing and confirmed sync loops.
- [x] **Optimization & Performance**:
    - [x] `aiofiles` integration for non-blocking disk writes.
    - [x] Global concurrency settings and sidebar config modal.
- [x] **Sync UI & Confirmation Refinement** (2026-02-25):
    - [x] **Interactive Modals**: Implemented interactive dropdowns with zero-indentation lists in the Confirm Sync dialog.
    - [x] **Dynamic Visuals**: Added a disk space impact bar with a linear scale and a 1% visibility floor.
    - [x] **Formatting Precision**: Added hanging indents for wrapped filenames and friendly name normalization (unquoting, space conversion).
    - [x] **Calculation Integrity**: Fixed total sync size summing to include updated files.
- [x] **UI Revision & Polish** (2026-03-01):
    - [x] **Terminology Shift**: Updated "Full" structure to "Flat" across all UI and translations.
    - [x] **Settings Relocation**: Moved Debug Mode to global settings modal.
    - [x] **Step 2 Layout Overhaul**: Implemented aggressive header suction and fractional column alignment for a compact, pixel-perfect wizard.
    - [x] **Dynamic Toggles**: Upgraded NotebookLM master toggle with mathematical `(x/y)` counter logic.
- [x] **NotebookLM Compatible Download Suite** (2026-03-01):
    - [x] **PPTX/PPT to PDF**: `pdf_converter.py` natively converts presentations via COM.
    - [x] **DOC/RTF to PDF**: `word_converter.py` natively converts legacy documents via COM.
    - [x] **HTML to Markdown**: `md_converter.py` cleanly strips Canvas Pages.
    - [x] **Code to TXT**: `code_converter.py` safely appends `.txt` to ~50 programming/data formats.
    - [x] **URL Compiler**: `url_compiler.py` scrapes `.url` shortcuts into a single master text file.
    - [x] **Video to Audio**: `video_converter.py` pulls `.mp3` tracks out of heavy `.mp4/.mov` payloads.
    - [x] **Excel to PDF**: `excel_converter.py` converts spreadsheets to 1-page-wide PDFs to maintain tabular structure.
    - [x] **Archive Extractor**: `archive_extractor.py` unzips payloads, dropping a 0-byte `.extracted` ghost stub to satisfy the sync engine.
    - [x] **Manifest Updating**: Mimicking native Canvas files by updating paths and hashes seamlessly.
    - [x] **UI Hijacking**: Dynamic reassignment of the main progress bar for post-processing phases.
    - [x] **State Persistence**: Streamlit widget cleanup bypass logic for post-UI execution constraints.
- [x] **Sync Engine Polish & UX Iteration** (2026-02-27):
    - [x] **Dashed Row Separators**: Robust CSS Flexbox implementation using keyed container scoping.
    - [x] **Filter Paradigm**: Opt-out selection logic with indeterminate state `(x/y)` display.
    - [x] **Expander Persistence**: Fixed Trash expander collapse using `keep_ignored_open` state flag.
    - [x] **Analysis Progress**: Ported standard download progress bar to the analysis phase.
    - [x] **Terminal Clarity**: Real-time log rendering decoupled from UI throttling.
- [x] **Sync Review UI Final Polish** (2026-02-28):
    - [x] **Dynamic Counters**: Live selection tracking (`selected / total`) in expander titles.
    - [x] **Batch Sync Crash Fix**: Resolved `StreamlitDuplicateElementKey` bug by implementing dynamic container keys (`cat_new_{course.id}`) and wildcard CSS pseudo-element injection.
    - [x] **Phase 1 Global Cancel**: Added a unified "Cancel Analysis" button to safely abort multi-course Canvas scanning.
    - [x] **Scoped Layout Refinements**: Fixed button row margins, tightened flush header padding, and added inter-course 20px spacing gaps.
    - [x] **Batch Tracking**: Injected blue numbered indices (`1.`, `2.`, etc.) into course headers for better orientation.
- [x] **Synthetic Shortcut & LTI Link Sync** (2026-02-27):
    - [x] **Manifest Tracking**: Support for Pages, ExternalUrls, and ExternalTools in `.canvas_sync.db`.
    - [x] **Negative ID Pattern**: Using negative integers for synthetic objects to prevent database PK collisions.
    - [x] **Sync Restore Logic**: Intercepting and recreating shortcut files during sync restoration.
    - [x] **Diffing Bypass**: Ignoring timestamps for synthetic items to support "Missing vs Up-to-date" logic.

## Completed Milestones (Archive)
- [x] Sync Feature Refactoring (2026-02-11)
- [x] Sync Robustness & Reliability Phase (2026-02-11)
- [x] UI Polish & Error Resilience (2026-02-15)
- [x] Advanced Sync Polish & UX Iteration (2026-02-21)
- [x] Sync Engine SQLite Migration & Heuristics Phase (2026-02-21)

## Current Status
- Application UI is professional, high-performance, and feature-complete, with robust sync analysis and real-time download dashboards.
- Sync engine handles all file types including synthetic shortcuts, with high-fidelity UI tracking.

## Pending Tasks
- [ ] Manual end-to-end testing with live multisession Canvas instances.
- [ ] Package updated version with PyInstaller.
- [x] Documentation updates and user walkthrough finalization.
