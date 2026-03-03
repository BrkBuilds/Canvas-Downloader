# Active Context: Canvas Downloader

## Current Focus
- **Post-Processing Logging & UI Cleanup**: Wired up all 8 NotebookLM post-processing hooks to dual-log to `debug_log.txt` and `download_errors.txt`. Refactored the Step 2 NotebookLM sub-toggles into a collapsible `st.expander` and removed legacy CSS indentation hacks.

## Recent Changes (Session 2026-03-02)
- **Post-Processing Dual Logging**:
  - Added a setup block in `app.py` (before all NotebookLM hooks) that imports `log_debug` from `canvas_debug`, computes `debug_file` from session state, and defines a `log_post_process_error()` helper for writing to `download_errors.txt`.
  - Added 32 `log_debug()` calls across all 8 hooks (start, progress, success, error, complete messages) — plain text is mirrored to `debug_log.txt` when Debug Mode is on.
  - Added 7 `log_post_process_error()` calls on every ❌ failure path, writing timestamped entries to `download_errors.txt` with a `[Post-Processing]` tag.
  - `sync_ui.py` confirmed to have zero post-processing hooks — no changes needed.
- **NotebookLM UI Refactor (Step 2)**:
  - Removed the `st.expander` wrapper for the 8 NotebookLM sub-settings.
  - Placed sub-checkboxes directly beneath the master toggle and injected custom "Tree-View" CSS targeting their widget keys (`.st-key-convert_zip`, etc.).
  - The CSS structurally nests the items with a 28px margin, 2px solid left-border (#3E4353), and tightened vertical padding, creating a clear visual parent-child relationship without Python indentation rules.

## Recent Changes (Session 2026-03-02 - Excel COM Polish)
- **Robust Excel COM Converter Rewrite**:
  - **Removed CountA() Inspection**: Discovered that calling `CountA` on 17-billion-cell Excel sheets hung the COM thread, causing RPC timeouts and cascading batch failures. Removed all sheet data inspection.
  - **Removed ActiveWindow Selection**: Headless COM without a visible UI often fails to instantiate an `ActiveWindow`, crashing `SelectedSheets.ExportAsFixedFormat`.
  - **Global Export Strategy**: Simplified script to export the entire workbook via `wb.ExportAsFixedFormat` regardless of empty sheets. (Empty sheets safely produce small, valid PDFs).
  - **Proactive COM Health Checks**: Added `_is_alive()` ping (`self.app.Version`) at the start of every conversion to immediately detect and revive a COM channel silently corrupted by a previous file's `wb.Close()`.
  - **COM Throttling**: Added `time.sleep(0.3)` pauses between major COM commands to give the print spooler time to settle.
- **Global Append Logging**:
  - `debug_log.txt` and `download_errors.txt` now default to the root workspace directory rather than per-course folders.
  - Added programmatic course headers (e.g., `=== Post-Processing: CourseName ===`) injected into the single session log, preventing file overwrites during multi-course syncs.
- **Cancel UX Safety**: Added `try...except` guards around `progress_container.progress()` to prevent `NameError` crashes if a user cancels a download before the UI placeholder has fully rendered.

## Recent Changes (Session 2026-03-01 Revision)
- **Step 2 Download Settings Overhaul**:
  - **Terminology Pivot**: Changed "Full" download structure to "Flat" for better user clarity.
  - **Aggressive Header Suction**: Replaced native Streamlit markdown headers with custom HTML `h3` tags using `-25px` bottom margins to eliminate dead vertical space.
  - **Merged CSS Injection**: Combined scoped CSS `<style>` blocks with HTML headers in single `st.markdown` calls to remove implicit `div` wrapper gaps.
  - **Destination Alignment**: Implemented a `[1, 6]` fractional column ratio with a `28px` invisible spacer to horizontally and vertically align the "Select Folder" button with the "Path" input box.
- **Settings Relocation**:
  - **Debug Mode**: Moved "Enable Troubleshooting Mode (Debug Log)" from the main wizard view into the global `⚙️ Application Settings` modal.
- **NotebookLM Sync Logic**:
  - **Dynamic (x/y) Counter**: Implemented a mathematical sync logic for master/sub toggles that tracks current active features in real-time.

## Recent Changes (Session 2026-03-01 - NotebookLM Full Suite)
- **NotebookLM Compatible Download Expansion**:
  - **Archive Extraction (Ghost Stub)**: Built `archive_extractor.py` to automatically unzip `.zip` and `.tar.gz` payloads. Designed a 0-byte `.extracted` stub system to satisfy the sync engine and prevent endless re-downloads. Injected this step at the *very top* of the post-processing pipeline to ensure unpacked format-viable files (like raw HTML or PPTX trapped in a zip) are handed to downstream converters.
  - **Video to Audio**: Implemented `video_converter.py` using `moviepy` to rip `.mp3` tracks from massive `.mp4/.mov` payloads, deleting the original video to save space and enable NotebookLM transcription.
  - **Legacy Word to PDF**: Expanded the Win32COM architecture via `word_converter.py` to target `.doc`, `.rtf`, and `.odt` files, upgrading them to modern `.pdf` format.
  - **HTML to Markdown**: Built `md_converter.py` using `beautifulsoup4` and `markdownify` to strip Canvas Pages of nested HTML boilerplate and convert them into clean `.md` files.
  - **Code & Data Preservation**: Developed `code_converter.py` to intercept the top 50 student programming/data extensions (e.g., `.py`, `.java`, `.json`) and safely append a `.txt` suffix (e.g., `script_py.txt`) while enforcing UTF-8 encoding.
  - **URL Complier**: Engineered `url_compiler.py` to scrape directories for synthetic `.url` shortcuts and aggregate them into a single `NotebookLM_External_Links.txt` reference file per course.
  - **Win32COM PowerPoint to PDF**: (Previously Implemented) `pdf_converter.py` for `.pptx` and `.ppt`.
  - **Excel to PDF (Tabular Integrity)**: Built `excel_converter.py` to handle `.xlsx`, `.xls`, and `.xlsm`. Designed a specific `PageSetup` logic (`FitToPagesWide = 1`, `FitToPagesTall = False`, zero margins) to ensure wide spreadsheets are rendered as 1-page-wide, infinitely-tall PDFs, preserving tabular structure for LLM ingestion. Original files are deleted post-conversion.
  - **COM Context Manager Refactoring**: Upgraded the core Win32COM PDF converters (`pdf_converter.py`, `word_converter.py`, `excel_converter.py`) from isolated utility functions into Python Context Managers (`__enter__`, `__exit__`). Wrapped the download conversion loops in `app.py` directly inside these context managers to solve massive CPU bottlenecking. The heavy Office COM application is now initialized only *once* per entire file batch, rather than cold-booting and tearing down for every single file.
- **Streamlit UI Hijacking & Post-Processing**:
  - **Progress Bar Re-routing**: Prevented the download UI from appearing "frozen" at 100% by hijacking the main download progress bar, status text, and metrics placeholders to visually track the slow post-processing extraction/conversion loops.
  - **Native Terminal Hooks**: Removed isolated `st.status` expanders and injected the conversion progress directly into the custom `log_deque` / `terminal_log` HTML rendering loops.
- **Streamlit State & COM Debugging**:
  - **Widget Cleanup Bypass**: Fixed a bug where transitioning from the Settings Step to the Download Step destroyed the NotebookLM checkbox value. Captured the value into a `persistent_convert_pptx` state key precisely on button-click before `st.rerun()`.
  - **UI Thread Flushing**: Injected explicit `time.sleep(0.2)` pauses immediately after rendering the post-processing UI framework. This guarantees Streamlit completes the browser DOM paint before the thread locks up on heavy blocking Python or Win32COM operations.
  - **Office 365 Strict Constraints**: Wrapped `powerpoint.Visible = False` in a `try...except` block, safely bypassing modern click-to-run Office versions that throw exceptions when attempting to hide the application window.

## Recent Changes (Session 2026-02-28)
- **Batch Sync Stability & Duplicate Key Fixes**:
  - **Dynamic Container Keys**: Resolved `StreamlitDuplicateElementKey` bug by appending `_{course.id}` to all `st.container` keys in `sync_ui.py`.
  - **Wildcard CSS Scoping**: Updated the global expander styling to use wildcard attribute selectors (`div[class*="st-key-cat_new"]`), ensuring color-coded borders work across all dynamically keyed course blocks.
  - **Phase 1 Global Cancel**: Injected a unified "Cancel Analysis" button above the Canvas scanning loop, allowing users to safely abort Phase 1 of a multi-course sync.
- **Sync Review UI Layout Finalization**:
  - **Compact Headers & Numbering**: Reduced header bottom margin (16px → 4px) and padding for a slim profile; added blue index numbering (`1.`, `2.`, etc.) for batch tracking.
  - **Course Isolation Spacing**: Injected 20px physical gaps between course container blocks to prevent visual bleeding.
  - **Dynamic Expander Counters**: Live selection tracking (`selected / total`) projected via CSS `::after` ghost text to maintain expander persistence.
  - **Clean Title Formatting**: Replaced bullets (`•`) with double-space padding for a sleeker, symbol-free finish.
  - **Button Spacing Correction**: Fixed margin-collapsing on Bulk Selection buttons via keyed container overrides.
- **Progress Parity & Dialog Polish**:
  - **Vertical Centering**: Forced `st.dialog` to center-screen via global CSS injection.
  - **Frontend Yield Hack**: Implemented JS-triggered "hidden button" clicks to ensure modals unmount before heavy processing starts.

## Recent Changes (Session 2026-02-27)
- **Synthetic Shortcut Sync Support**:
  - **Manifest Integration**: Support for Pages, ExternalUrls, and ExternalTools using the "Negative ID Pattern" to prevent database collisions.
  - **LTI URL Priority Fix**: Prefer `html_url` for ExternalTools to ensure correct Canvas-wrapped authentication.
- **Sync Review UI Restructure**:
  - **Flush Header Band**: Negative margin bleed trick to create seamless course headers.
- **Synthetic Shortcut Sync Support**:
  - **Manifest Integration**: Modified `_save_page` and `_create_link` to return filepaths. Captured these in download loops to create `CanvasFileInfo` mock objects with negative IDs (e.g., `-int(item.id)`).
  - **Shortcut-Aware Live Fetching**: Upgraded `_get_files_from_modules` in `canvas_logic.py` to generate reciprocal mock objects during sync analysis, ensuring the Sync engine "sees" Pages and ExternalUrls as matching database entries.
  - **LTI URL Priority Fix**: Flipped extraction logic to strictly prefer `html_url` over `external_url`, ensuring ExternalTools route through the Canvas wrapper for correct JWT authentication.
  - **Size Normalization**: Hardcoded `size=0` for all synthetic items across both Manifest generation and Live Fetching to prevent perpetual "Update Available" size mismatches.
- **Sync Engine Reconciliation**:
  - **Negative ID Bypass**: Injected a bypass in `sync_manager.py`'s `_is_canvas_newer()` function. If `canvas_file.id < 0`, the engine skips timestamp comparison (which is unreliable for module items) and falls through to a strict local existence check.
  - **Restoration Interception**: Modified `sync_ui.py`'s download batch loop to detect negative IDs and recreate `.url`/`.html` shortcut files directly using Pathlib instead of attempting an HTTP byte-download.
- **Sync Execution UI Overhaul**: (Previous session changes maintained...)
  - **Speed & ETA Dashboard**: Replaced the static Streamlit text metric with a sleek, injected HTML/CSS 4-column dashboard rendering Sync Progress (X/Y), Downloaded (MB), Speed (MB/s), and ETA (MM:SS).
  - **Live Terminal Log**: Added a native-looking terminal window tracking active asynchronous downloads in real-time. Checkmarks and cross emojis visually categorize file successes, skips, and failures.
- **Sync Review Feature Fixes**:
  - **Ignored Files Rendering**: Fixed a conditional block that hid the analyze summary if zero actionable files existed; the section now persists if `total_ignored > 0`.
  - **Locally Deleted Binding**: Checkboxes for manually deleted local files now initialize by checking the global aggregate filters before falling back to False.
  - **Key Synchronization**: Unified all file-level checkbox keys to use `course_id`, ensuring state Persistence across filter changes.
  - **Zero-Value Metric Card Muting**: Transitioned from static HTML cards to a dynamic `_render_metric_card` Python helper. Zero-value cards intelligently drop their background opacity to 10% and remove box-shadows.
- **Confirm Sync Modal UX**:
  - **Vertical Centering**: Injected CSS globally within Step 4 to force `st.dialog` to appear dead-center in the viewport.
  - **Immediate Closure Strategy**: Implemented a "Frontend Yield" hack using a hidden button click triggered by a 200ms `setTimeout` JS script.
- **Standard Download UX Parity**:
  - **Confirmation Dialog**: Ported the `@st.dialog` vertical centering modal logic over to `app.py` Step 2.
  - **Dashboard Analytics**: Upgraded the standard download progress block (Step 3) to strictly utilize the injected HTML Sync metrics rendering structure.

## Active Tasks
- [x] Implement robust Row Separator CSS using keyed container scoping
- [x] Implement Opt-Out filter paradigm and fix state-lock bugs
- [x] Port Sync Progress UI to Analysis phase
- [x] Refine Trash/Ignored UX (Clean grey text, Persistent expander)
- [x] Fix terminal log rendering lag by immediate markdown updates
- [x] Standardize filename unquoting across all UI components
- [x] Refine "Select files to sync" box (Group header, filter options, and global uncheck buttons)
- [x] Refine "Sync Review" expanders (Wrap course blocks in master containers)

## Architecture Notes
- **Scoped Layout Overrides**: Use `st.container(key="...")` combined with targeted CSS (e.g., `.st-key-X > div[data-testid="stVerticalBlock"]`) to override Streamlit's default 1rem gaps without affecting the rest of the application.
- **Separator Tightening**: Targeting `hr` within keyed containers allows for pixel-perfect vertical positioning of logical dividers.
- **Idempotent Data Mutation**: When writing state callbacks tied to `st.button` `on_click` events in Streamlit, always ensure the array manipulations are strictly idempotent. Rapidly double-clicking buttons triggers the event twice before the rendering loop executes, leading to duplicate entities in session-state arrays which subsequently crashes Streamlit if those entries dynamically generate widget keys.
- **Frontend Yield for Dialogs**: When starting a heavy, blocking task immediately after closing an `st.dialog`, use a hidden button click triggered via `components.html` with a small JS timeout (e.g., 200ms). This allows the Streamlit frontend to receive the "unmount modal" command and clear the UI before the Python server locks up on the heavy processing loop.
