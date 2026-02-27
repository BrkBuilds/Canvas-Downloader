# Active Context: Canvas Downloader

## Current Focus
- **Archiving Synthetic Logic**: Just completed full integration of synthetic shortcuts (Pages, Links, LTI Tools) into the Sync Manifest and Restoration engine.

## Recent Changes (Session 2026-02-27)
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
  - **Live Terminal Log**: Added a native-looking terminal window tracking active asynchronous downloads in real-time, managed efficiently via an in-memory `collections.deque(maxlen=10)` and HTML injection to prevent heavy Streamlit re-renders. Checkmarks and cross emojis visually categorize file successes, skips, and failures.
  - **Cancel Button Realignment**: Fixed the Cancel button's alignment by ensuring it renders natively to the left below the log container rather than in an enforced column structure.
- **Sync Review Feature Fixes**:
  - **Ignored Files Rendering**: Fixed a conditional block that hid the analyze summary if zero actionable files existed; the section now persists if `total_ignored > 0`.
  - **Locally Deleted Binding**: Checkboxes for manually deleted local files now initialize by checking the global aggregate filters (extensions and "Select All") before falling back to False.
  - **Key Synchronization**: Unified all file-level checkbox keys to use `course_id` (not `idx`), ensuring state Persistence across filter changes and preventing payload extraction errors.
  - **Zero-Value Metric Card Muting**: Transitioned from static HTML cards to a dynamic `_render_metric_card` Python helper. Zero-value cards intelligently drop their background opacity to 10%, remove box-shadows, and apply a subtle colored border to dramatically reduce visual clutter while preserving readability.
- **Confirm Sync Modal UX**:
  - **Vertical Centering**: Injected CSS globally within Step 4 to force `st.dialog` to appear dead-center in the viewport by setting `display: flex !important` and `align-items: center !important` on the modal container.
  - **Immediate Closure Strategy**: Implemented a "Frontend Yield" hack using a hidden button click triggered by a 200ms `setTimeout` JS script. This ensures the React DOM can unmount the modal before the heavy Python sync loop starts, preventing the modal from being "stuck" or "greyed out" on screen while processing.
- **Standard Download UX Parity**:
  - **Confirmation Dialog**: Ported the `@st.dialog` vertical centering modal logic over to `app.py` Step 2 to pause standard download execution until explicit user confirmation.
  - **Modal Optimization**: Refined the dialog to load instantly by deferring heavy file/size calculations to Step 3. Removed the technical `HIDDEN_START` button hack.
  - **Smart Course Display**: Implemented conditional rendering in the modal; showing a static row for single course selections and a clean dropdown for multiple courses.
  - **Dashboard Analytics**: Upgraded the standard download progress block (Step 3) to strictly utilize the injected HTML Sync metrics rendering structure in an `st.empty()` block, including the new 4-column "Files" count configuration.
  - **Routing Rescue (No-Hang)**: Fixed the Standard Download async sequence leaking on large file completions by re-routing the execution end directly to Step 4.

## Active Tasks
- [x] Refine "Select files to sync" box (Tighten layout, Remove emojis)
- [x] Refine "Confirm Sync" dialog (Dropdowns, Dynamic Bar)
- [x] Refine "Sync Review" expanders (Top padding, Trash layout, Button styling)
- [x] Fix `StreamlitDuplicateElementKey` race condition
- [x] Vertically center and fix closure logic for Sync Confirmation dialog
- [x] Implement Zero-Value muting for Sync Review metric cards
- [x] Implement high-visibility Speed & ETA custom metrics dashboard
- [x] De-noise Live Terminal logger and add Active Downloading status indicator
- [x] Fix "Hanging Completion" bug by forcing Streamlit state change and `st.rerun()`
- [x] Port Sync Metrics and Terminal UI to Standard Download

## Architecture Notes
- **Scoped Layout Overrides**: Use `st.container(key="...")` combined with targeted CSS (e.g., `.st-key-X > div[data-testid="stVerticalBlock"]`) to override Streamlit's default 1rem gaps without affecting the rest of the application.
- **Separator Tightening**: Targeting `hr` within keyed containers allows for pixel-perfect vertical positioning of logical dividers.
- **Idempotent Data Mutation**: When writing state callbacks tied to `st.button` `on_click` events in Streamlit, always ensure the array manipulations are strictly idempotent. Rapidly double-clicking buttons triggers the event twice before the rendering loop executes, leading to duplicate entities in session-state arrays which subsequently crashes Streamlit if those entries dynamically generate widget keys.
- **Frontend Yield for Dialogs**: When starting a heavy, blocking task immediately after closing an `st.dialog`, use a hidden button click triggered via `components.html` with a small JS timeout (e.g., 200ms). This allows the Streamlit frontend to receive the "unmount modal" command and clear the UI before the Python server locks up on the heavy processing loop.
