# Progress: Canvas Downloader

## Completed Milestones
- [x] **Project Initialization**: Repository setup and initial architecture.
- [x] **Core Downloader**: Bulk downloading of course files/modules.
- [x] **Smart Sync Feature**:
    - [x] `SyncManager` class implementation and SQLite migration.
    - [x] UI for folder-course pairing and confirmed sync loops.
- [x] **Unified UI Status & Desync Fix** (2026-03-04):
    - [x] **Desync Resolution**: Segregated filename status updates from throttled UI blocks in Phase 2.
    - [x] **Universal Visibility**: Ported blue `#38bdf8` status text to all 14 post-processing loops cross-app.
- [x] **Atomic Symbiosis & DB Integrity** (2026-03-03):
    - [x] **Atomic Upserts**: Replaced destructive manifest DB overwrites with row-by-row `INSERT OR REPLACE`.
    - [x] **`.part` File Streaming**: Files stream to `.part` and are atomically renamed strictly at 100% completion (deployed in both `app.py` and `sync_ui.py`).
    - [x] **Mid-Chunk Cancellation**: Instant cancellation flags injected directly into the 1MB `async for` read loops for immediate file unlinking.
    - [x] **Semantic Purity Guards**: Relocated final `save_manifest()` calls to fire *after* all cancel evaluations, assuring mathematical parity between disk and DB on aborted syncs.
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
    - [x] **COM Context Manager Refactoring**: Re-architected Word, PPTX, and Excel PDF converters from single-shot functions into Context Managers (`__enter__`, `__exit__`), resulting in massive performance gains by avoiding COM cold-boots natively per file.
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
- [x] **Sync Review UI Final Polish** (2026-02-28 & 2026-03-03):
    - [x] **Quick Sync Interceptor Full Integration**: Fixed Quick Sync bypassing logic by including `locally_deleted_files` correctly in the `redownload` payload, persisting post-processing flags, and enforcing strict session state resets on invocation.
    - [x] **Dynamic Counters**: Live selection tracking (`selected / total`) in expander titles.
    - [x] **Batch Sync Crash Fix**: Resolved `StreamlitDuplicateElementKey` bug by implementing dynamic container keys (`cat_new_{course.id}`) and wildcard CSS pseudo-element injection.
    - [x] **Phase 1 Global Cancel**: Added a unified "Cancel Analysis" button to safely abort multi-course Canvas scanning.
    - [x] **Scoped Layout Refinements**: Fixed button row margins, tightened flush header padding, and added inter-course 20px spacing gaps.
    - [x] **Batch Tracking**: Injected blue numbered indices (`1.`, `2.`, etc.) into course headers for better orientation.
- [x] **Microscopic Cancel UX Perfection** (2026-03-03):
    - [x] **Phase 1 Parity**: Unified cancellation string to strictly read "Cancelled during Course Analysis." across both Standard and Sync modes.
    - [x] **State Bleed**: Hard-guarded `_run_sync` with `st.rerun()` early-returns to prevent Phase 2 cancellations from triggering Phase 3 UI states.
    - [x] **COM Render Lock Bypass**: Successfully forced the Post-Processing cancel button to render during heavy Excel/PPTX conversions by reusing an immune DOM placeholder and strictly enforcing a 300ms thread sleep.
- [x] **Synthetic Shortcut & LTI Link Sync** (2026-02-27):
    - [x] **Manifest Tracking**: Support for Pages, ExternalUrls, and ExternalTools in `.canvas_sync.db`.
    - [x] **Negative ID Pattern**: Using negative integers for synthetic objects to prevent database PK collisions.
    - [x] **Sync Restore Logic**: Intercepting and recreating shortcut files during sync restoration.
    - [x] **Diffing Bypass**: Ignoring timestamps for synthetic items to support "Missing vs Up-to-date" logic.
- [x] **Post-Processing Logging & UI Cleanup** (2026-03-02):
    - [x] **Dual Logging**: Wired 32 `log_debug()` calls and 7 `log_post_process_error()` calls across all 8 NotebookLM post-processing hooks in `app.py`.
    - [x] **Expander Refactor**: Moved sub-toggles into `st.expander` and removed legacy CSS indentation hacks.
- [x] **Excel COM Robustness Polish** (2026-03-02):
    - [x] **Removed CountA() Overload**: Removed 17-billion-cell dataset inspection which hung the COM thread and triggered RPC timeouts.
    - [x] **Global Export**: Exporting entire workbook (including empty sheets) to bypass the missing `ActiveWindow` headless COM crash.
    - [x] **Proactive Revival**: Added `_is_alive()` ping (`self.app.Version`) at the start of every iteration to immediately detect and revive a silently corrupted COM object channel.
    - [x] **Throttling**: Added `time.sleep(0.3)` pauses after the `Open` and `Export` commands.
    - [x] **Session Global Log Headers**: `debug_log.txt` now sits globally in the workspace with automatically injected Course Headers.

## Completed Milestones (Archive)
- [x] Sync Feature Refactoring (2026-02-11)
- [x] Sync Robustness & Reliability Phase (2026-02-11)
- [x] UI Polish & Error Resilience (2026-02-15)
- [x] Advanced Sync Polish & UX Iteration (2026-02-21)
- [x] Sync Engine SQLite Migration & Heuristics Phase (2026-02-21)

## Current Status
- Application UI is professional, high-performance, and feature-complete, with robust sync analysis and real-time download dashboards.
- Sync engine handles all file types including synthetic shortcuts, with high-fidelity UI tracking.
- Post-processing pipeline now has complete observability via dual logging to `debug_log.txt` and `download_errors.txt`.

## Pending Tasks
- [ ] Manual end-to-end testing with live multisession Canvas instances.
- [ ] Package updated version with PyInstaller.
- [x] Documentation updates and user walkthrough finalization.
