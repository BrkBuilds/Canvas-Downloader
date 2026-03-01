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

## Synchronous API Integration Patterns (Win32COM)
- **Widget Cleanup Bypass via Button Hooks**:
    - *Problem*: Transitioning from a step with an active widget (e.g., a checkbox) to a new step destroys the widget and deletes its key from `st.session_state`.
    - *Solution*: Capture the widget's boolean state into a custom, non-widget `persistent_` session state key directly inside the `if st.button('Next'):` execution block, immediately before the app reruns.
- **UI Thread Flushing**:
    - *Problem*: Initiating heavy blocking synchronous calls (like `PowerPoint.Application.SaveAs`) immediately after rendering new Streamlit placeholders causes the backend to lock up before the frontend DOM has time to paint the new UI state.
    - *Solution*: Inject an explicit `time.sleep(0.2)` explicitly between rendering the loading UI and initiating the blocking COM thread to guarantee frontend synchronization.
- **Office 365 COM Visibility Bypass**:
    - *Problem*: Modern click-to-run Office 365 environments throw `Invalid request` exceptions when attempting to coerce `Application.Visible = False`.
    - *Solution*: Wrap visibility attribute coercions in a `try...except` block, allowing the COM script to fall back to a visible window state if security constraints prevent hidden execution.

## Synchronization Strategy
- **SQLite Manifest Tracking**: Stores metadata (ID, path, size, date) for 1:1 mapping.
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
