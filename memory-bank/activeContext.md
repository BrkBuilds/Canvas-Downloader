# Active Context: Canvas Downloader

## Current Focus
- **Final Sync UI & Verification**: Completed the absolute final polish of the Sync Review UI, including live selection counters, clean category spacing, and scoped CSS layout corrections. Transitioning to manual end-to-end verification.

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
