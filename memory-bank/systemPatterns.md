# System Patterns: Canvas Downloader

## Core Architecture
Modular design centered around Streamlit for UI and CanvasAPI for backend communication.

### File Structure
- **`app.py`**: Main entry point, UI controller.
- **`sync_ui.py`**: All sync-related UI logic.
- **`ui_helpers.py`**: Shared UI utilities (disk check, plurals, path utils).
- **`canvas_logic.py`**: Canvas API interactions.
- **`sync_manager.py`**: Sync backend (SQLite manifest, MD5 hashing, analysis engine).
- **`translations.py`**: Centralized i18n dictionary.
- **`excel_converter.py`**: Excel to PDF conversion utility using Win32COM.

## UI Architecture & Patterns
- **Modals**: Use **`st.dialog`** for complex isolated interactions.
- **Interactive Lists**: Use HTML `<details>` and `<summary>` inside modals to handle large file lists without overwhelming the main view.
- **Component Constriction**: Use fractional columns to limit component width on large screens.
- **Zero-Indentation HTML String Pattern**:
    - Streamlit's markdown parser converts indented HTML strings into `<pre><code>` blocks.
    - *Robust Pattern*: Construct long HTML/CSS strings in Python without any leading indentation on the multi-line closing quotes/content to ensure they render as raw HTML.
- **Flex-box Hanging Indent Pattern**:
    - To support emojis + multi-line text:
    - Use `display: flex; align-items: flex-start;` on `<li>`.
    - Wrap the icon in a fixed-width `span` (e.g., `24px`).
    - Wrap the text in a `flex:1` `span` with `word-break: break-word`.
- **Keyed Container Scoping for CSS Overrides**:
    - *Problem*: Streamlit's default margins/paddings on `st.columns` and `st.container` are often too loose for dense data lists.
    - *Solution*: Wrap targeted loops in `st.container(key="some_key")`. 
    - Injected CSS then uses partial attribute selectors `div[class*="st-key-some_key"]` to target the internal `stHorizontalBlock` (columns) or `stVerticalBlock` without polluting the global scope or colliding with other keyed instances in loops.
- **Wildcard Attribute Selector for Dynamic Widgets**:
    - *Problem*: When widget keys are dynamic (e.g., `key=f"cat_new_{course.id}"`), standard class selectors like `.st-key-cat_new` fail.
    - *Solution*: Use CSS wildcard attribute selectors `div[class*="st-key-cat_new"]` to target all dynamically keyed containers that share a common prefix. This allows a single global CSS block to style many unique widgets simultaneously.
- **Progress Bar Visibility Pattern**:
    - For disk space checks: `min(100, max(1, real_pct))` if `bytes > 0`.
    - Pure linear mapping on high-capacity drives makes small downloads look like 0% (invisibility). Always implement a 1% floor for any non-zero sync size.
- **Dynamic File Selection Counting (CSS Ghost Text) Pattern**:
    - *Problem*: Expander titles in Streamlit are used as their internal state ID. If you inject dynamic numbers (e.g. `[1 / 5]`) directly into the Python string `st.expander()`, the ID changes on every rerun. This destroys the user's open/closed state, causing them to forcefully pop open or snap shut unexpectedly.
    - *Solution*: Revert the expander title to a purely static string (e.g., `st.expander("🆕 New files")`). Calculate the `selectedCount` dynamically via a list comprehension on `st.session_state`. Then, project that string onto the screen by injecting a targeted `<style>` block that uses the `::after` CSS pseudo-element on the expander's summary tag. Streamlit's reactive rerun model updates the CSS instantly without destroying the widget state constraint.
- **Margin Collapse Override (Scoped CSS)**:
    - *Problem*: Streamlit's internal layout often swallows HTML `<div style='height:Xpx'>` spacers due to margin collapsing or negative margins on nearby components.
    - *Solution*: Wrap the target component (e.g., a button row) in a keyed `st.container` and use scoped CSS with `!important` on the `margin-top` of the `.st-key-...` class to force the desired vertical break.
- **Aggressive Header Suction Pattern**:
    - *Problem*: Native Streamlit `###` headers have large default bottom margins that create excessive dead space.
    - *Solution*: Replace with custom HTML `<h3 style='margin-bottom: -25px;'>` to forcefully pull widgets up against the header. Adjust margin-bottom per widget type (e.g., -10px for deeper widgets, -25px for flat ones).
- **Merged CSS/HTML Injection Pattern**:
    - *Problem*: Separate `st.markdown` calls for `<style>` and HTML headers create multiple hidden Streamlit wrapper `divs`, each adding extra vertical padding.
    - *Solution*: Bundle the CSS `<style>` block and the HTML `<h3>` tag into a *single* `st.markdown(unsafe_allow_html=True)` call to minimize div overhead.
- **Extreme Column Ratio Alignment Pattern**:
    - *Problem*: Default `st.columns(2)` splits are too wide for small buttons, pushing dependent content too far right.
    - *Solution*: Use extreme ratios like `[1, 6]` or `[1.2, 8.8]` to crush the trigger-widget's column, pulling the main input field horizontally into a tight layout.
- **Dynamic Master/Sub Syncing Pattern**:
    - *Problem*: Binary master toggles don't reflect how many sub-options are active.
    - *Solution*: Use a `TOTAL_SUBS` constant and calculate `active_subs = sum([...])` on every rerun. Use an f-string label for the master checkbox: `f"Master Label :gray[({active_subs}/{TOTAL_SUBS})]"` to provide real-time mathematical feedback.

## Synchronous API Integration Patterns (Win32COM)
- **COM Application Context Managers**:
    - *Problem*: Cold-booting and tearing down instances of Excel, Word, or PowerPoint for *every single file* in a batch download creates massive CPU overhead and severely bottlenecks post-processing speed.
    - *Solution*: Refactored `pdf_converter.py`, `word_converter.py`, and `excel_converter.py` into Python Context Managers (`__enter__`, `__exit__`). The `with ConverterClass() as converter:` block strictly wraps the outside of the file processing loops. This guarantees the heavyweight COM application is initialized exactly once per batch and safely exits securely when the block completes.
- **Widget Cleanup Bypass via Button Hooks**:
    - *Problem*: Transitioning from a step with an active widget (e.g., a checkbox) to a new step destroys the widget and deletes its key from `st.session_state`.
    - *Solution*: Capture the widget's boolean state into a custom, non-widget `persistent_` session state key directly inside the `if st.button('Next'):` execution block, immediately before the app reruns.
- **UI Thread Flushing**:
    - *Problem*: Initiating heavy blocking synchronous calls (like `PowerPoint.Application.SaveAs`) immediately after rendering new Streamlit placeholders causes the backend to lock up before the frontend DOM has time to paint the new UI state.
    - *Solution*: Inject an explicit `time.sleep(0.2)` explicitly between rendering the loading UI and initiating the blocking COM thread to guarantee frontend synchronization.
- **Office 365 COM Visibility Bypass**:
    - *Problem*: Modern click-to-run Office 365 environments throw `Invalid request` exceptions when attempting to coerce `Application.Visible = False`.
    - *Solution*: Wrap visibility attribute coercions in a `try...except` block, allowing the COM script to fall back to a visible window state if security constraints prevent hidden execution.
- **Proactive COM Health Checks (`_is_alive`)**:
    - *Problem*: Repeatedly opening and closing files via headless COM often silently corrupts the RPC channel. The COM object reference (`self.app`) remains non-None, but the next `Workbooks.Open` command crashes.
    - *Solution*: Implement a lightweight method (`try: self.app.Version`) at the very start of the `convert()` loop. If the ping fails, immediately execute the self-healing routine (`Quit()` + `_init_app()`) *before* attempting the actual file conversion.
- **Headless COM Throttling**:
    - *Problem*: Sequential high-speed COM operations (`Open` -> `Export` -> `Close`) outpace the physical hardware spooler or thread release, destabilizing batch loops.
    - *Solution*: Explicitly inject small `time.sleep(0.3)` pauses between massive synchronous milestones (e.g., ExportAsFixedFormat) to give the application time to stabilize the thread.

## NotebookLM Data Pipeline Patterns
  - **Excel to PDF (Tabular Integrity & Global Export)**:
    - *Pattern*: Unlike Word/PPT, Excel sheets are "infinite". To ensure LLM readability, the system modifies `PageSetup` to `FitToPagesWide = 1` and `FitToPagesTall = False`, while setting all margins to 0. 
    - *Anti-Pattern Avoidance*: Never attempt to select sheets via `ActiveWindow` or filter data via `WorksheetFunction.CountA(sheet.Cells)`. `ActiveWindow` crashes reliably in `Visible=False` environments, and `CountA` sweeps billions of cells causing guaranteed RPC timeouts. The cleanest strategy is to just export the entire workbook via `ExportAsFixedFormat(0)`—empty sheets will produce small harmless PDFs instead of crashing the batch pipeline.
- **The Ghost Stub Pattern (Archive Extraction)**:
    - *Problem*: Automatically extracting large `.zip` / `.tar.gz` payloads after download creates massive file duplication, but deleting the original archive causes the sync engine to endlessly re-download it.
    - *Solution*: Extract the contents, delete the original archive, and instantly drop a 0-byte `.extracted` file matching the original archive's name. Update the SQLite manifest `local_path` to point to this stub, preserving sync integrity without wasting disk space.
- **Top-of-Pipeline Extraction**:
    - *Pattern*: Always run Archive Extraction *before* any other post-processing hook (like HTML->MD or Code->TXT). This ensures files liberated from a student's ZIP folder are caught by the subsequent loops and format-shifted properly.
- **Manifest Translation**:
    - *Pattern*: When converting a file (e.g., `.pptx` to `.pdf`), the system updates the `local_path`, `original_size`, and `original_md5` in the database to match the new derivative file, but preserves the original `canvas_filename`. This effectively tricks the sync diffing engine into linking a remote PPTX to a local PDF for version control.

## Synchronization Strategy & Data Integrity
- **SQLite Manifest Tracking**: Stores metadata (ID, path, size, date) for 1:1 mapping.
- **Atomic Symbiosis Pattern**:
    - *Problem*: Crashes, immediate cancellations, or network failures during file downloads historically corrupted the SQLite manifest or left halfway-written files on disk, leading to "Cancel Ghosting" (0 files to sync on retry).
    - *Solution 1 (Atomic Upserts)*: Replaced destructive `DELETE FROM` bulk sweeps with per-row `INSERT OR REPLACE` upserts in `save_manifest()`.
    - *Solution 2 (The `.part` Pattern)*: All active downloads append a `.part` extension to the filename during streaming. Cancel checks fire every 1MB chunk. If interrupted or cancelled, the `.part` file is unlinked. The file is only atomically renamed to its final extension upon 100% byte verification.
    - *Solution 3 (Semantic Purity Guards)*: DB commit loops (`save_manifest` and `_save_single_file_to_db`) strictly occur *after* all physical disk verification is complete, and are shielded by top-level execution guards (e.g., `if st.session_state.sync_cancelled: st.rerun()`) to ensure zero database mutations occur during a cancelled session.
- **Negative ID Pattern**: Synthetic shortcuts (Pages, ExternalUrls, ExternalTools) are assigned `id = -int(item.id)`. This keeps them unique and prevents primary key collisions with physical Canvas `File` objects in SQLite.
- **Shortcut Bypass Logic**: `_is_canvas_newer()` in `sync_manager.py` explicitly returns `False` for `id < 0`. This bypasses unreliable module timestamps and forces the engine to rely on local existence checks.
- **Sync Restoration Interception**: The download pipeline in `sync_ui.py` intercepts negative IDs and recreates `.url` or `.html` files locally using static templates rather than performing an HTTP GET.
- **URL Extraction Priority**: For synthetic shortcuts, `html_url` is prioritized over `external_url` to ensure LTI tools route through the Canvas wrapper for authentication.
- **Deduplication**: Files are deduplicated by calculated target path and size to handle identical items linked in multiple modules.
- **Analysis Engine**: Diffing Canvas vs Local Manifest vs Local Disk.
- **Path Determination**: `detect_structure()` must precede analysis to correctly calculate relative paths for "Flat" vs "Folders" modes.

## Error Handling & Logging
- **Locked File Pruning**: Pre-filtering Canvas `File` objects for missing `url` attributes to prevent batch download crashes.
- **LTI/Media Catch**: Graceful reporting of restricted media streams via extension/URL inspection.
- **Centralized Logs**: `download_errors.txt` created in the workspace root.
- **Post-Processing Dual Logging Architecture**:
    - `canvas_debug.log_debug(message, debug_file)` — writes timestamped plain text to `debug_log.txt` (gated by Debug Mode toggle). The `debug_file` is `Path(save_dir) / "debug_log.txt"` or `None`.
    - `log_post_process_error(directory, filename, error_msg)` — inline helper defined in `app.py` that appends `[Post-Processing]`-tagged entries to `download_errors.txt` (always active on failures).
    - Every post-processing log message is mirrored to three destinations: `log_deque` (Streamlit terminal UI), `logger.info/error` (Python logging), and `log_debug` (debug file).

## UI Collapsible Settings Pattern
- **Expander for Sub-Toggles**:
    - *Problem*: 8+ sub-checkboxes clutter the Step 2 UI and visually overwhelm the page.
    - *Solution*: Keep the master toggle (`notebooklm_master`) always visible, and nest all sub-checkboxes inside `st.expander(f"⚙️ Advanced Conversion Settings ({active}/{total})")`. The dynamic label updates on rerun. No custom CSS indentation needed — the expander provides natural visual hierarchy.
