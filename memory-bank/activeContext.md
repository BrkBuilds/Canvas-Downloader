# Active Context: Canvas Downloader

## Current Focus
- **UI/UX Refinement Phase**: Perfecting the "Confirm Sync" dialog aesthetics and the "Sync Review" page layout logic.

## Recent Changes (Session 2026-02-25)
- **Sync Review UI Layout Tightening**:
  - **Emoji Removal**: Cleaned up "Select All" and "Deselect All" buttons by removing decorative emojis.
  - **Filter Box Compression**: Applied targeted CSS scoping via `.st-key-sync_filter_box_outer` to reduce vertical gaps, tighten separator margins, and minimize label spacing within the filetype selector.
  - **Bulk Button Polish**: Cleaned up the 'Missing', 'Updated', and 'New' section expanders by removing caption text, making the 'Ignore Unchecked' sweep button span full-width without columns, and injecting CSS rules to reduce the padding making it a subtle size.
  - **Trash UI Sync**: Refactored the 'Ignored Files' section to completely match the active files layout by applying `vertical_alignment="center"` using identical column distributions `[0.92, 0.08]`. Added a "Restore All Ignored Files" button to the top of the expander.
- **State Logic Fixes**:
  - **Callback Idempotency**: Refactored all data-mutating UI callbacks (`handle_ignore`, `handle_restore`, `handle_sweep`, `handle_restore_all`) to be strictly idempotent. When appending a file object to a session state array (like `ignored_files`), the logic now pre-verifies the ID doesn't already exist. Similarly, when removing, it uses list comprehensions to sweep out all potential duplicates. This prevents `StreamlitDuplicateElementKey` errors during rapid spam-clicking.
  - **Widget Key Deduplication**: All checkbox and button keys inside the `sync_ui` file loops have had their loop `idx` integers completely removed, relying solely on `canvas_file_id` and `course_id` to form robust, unique rendering keys.
  - **Sync Button Edge Case Check**: The global `Sync Selected` button is now dynamically disabled with an error prompt if all files across all courses are actively ignored by the user.

## Active Tasks
- [x] Refine "Select files to sync" box (Tighten layout, Remove emojis)
- [x] Refine "Confirm Sync" dialog (Dropdowns, Dynamic Bar)
- [x] Refine "Sync Review" expanders (Top padding, Trash layout, Button styling)
- [x] Fix `StreamlitDuplicateElementKey` race condition

## Architecture Notes
- **Scoped Layout Overrides**: Use `st.container(key="...")` combined with targeted CSS (e.g., `.st-key-X > div[data-testid="stVerticalBlock"]`) to override Streamlit's default 1rem gaps without affecting the rest of the application.
- **Separator Tightening**: Targeting `hr` within keyed containers allows for pixel-perfect vertical positioning of logical dividers.
- **Idempotent Data Mutation**: When writing state callbacks tied to `st.button` `on_click` events in Streamlit, always ensure the array manipulations are strictly idempotent. Rapidly double-clicking buttons triggers the event twice before the rendering loop executes, leading to duplicate entities in session-state arrays which subsequently crashes Streamlit if those entries dynamically generate widget keys.
